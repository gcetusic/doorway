from asyncio import CancelledError
import json

from aiohttp import web, hdrs, ClientSession
from aiopg.sa import create_engine

from middlewares import BasicAuthMiddleware, RequestAuthorizationMiddleware


@web.middleware
async def routing(request, handler):
    merchant = request.match_info.get('merchant')
    channel = request.rel_url.query['channel']

    # Check if there is route for the specified merchant/channel
    for entry in [f'{merchant}:{channel}', f':{channel}', f'{merchant}:']:
        route = app['configuration']['routes'].get(entry)
        if route is not None:
            request['address'] = f"ws://{route['address']}/{merchant}/products"
            break
    else:
        return web.Response(status=web.HTTPNotFound.status_code)

    return await handler(request)


basic_auth = BasicAuthMiddleware()
request_authz = RequestAuthorizationMiddleware()


async def manage_connection(app):
    app['db'] = await create_engine(
        user='registrar',
        database='registry',
        host='localhost',
        port=5432,
        password='123123123'
    )
    app['listener'] = app.loop.create_task(listen(app))

    yield
    
    app['listener'].cancel()
    await app['listener']
    app['db'].close()
    await app['db'].wait_closed()


async def listen(app):
    async with app['db'].acquire() as conn:
        await conn.execute('LISTEN routes')
    try:
        while True:
            msg = await conn.connection.notifies.get()
            payload = json.loads(msg.payload)
            action = payload['action']
            route = payload['data']
   
            if action == 'DELETE':
                del app['configuration']['routes'][
                    f"{route['merchant']}:{route['channel']}"
                ]
            else:
                app['configuration']['routes'][f"{route['merchant']}:{route['channel']}"] = {
                    'address': route['address'],
                    'users': [] if route['users'] is None else [str(user) for user in route['users']]
                }
    except CancelledError:
        pass
    finally:
        await conn.execute('UNLISTEN routes')


async def load_configuration(app):
    app['configuration'] = {
        'routes': {}
    }

    # Load routes
    async with app['db'].acquire() as conn:
        async for row in conn.execute('SELECT * FROM routes'):
            app['configuration']['routes'][f'{row.merchant}:{row.channel}'] = {
                'address': row.address,
                'users': [] if row.users is None else [str(user) for user in row.users]
            }


async def stream(request):
    # Start streaming the data as soon as it becomes available
    response = web.StreamResponse(
        status=web.HTTPOk.status_code,
        headers={hdrs.CONTENT_TYPE: 'text/html'})

    await response.prepare(request)

    async with ClientSession() as session:
        async with session.ws_connect(request['address']) as ws:
            async for msg in ws:
                await response.write(msg.data.encode('utf-8'))

    return response


app = web.Application(middlewares=[
    basic_auth,
    request_authz,
    routing
])

app.cleanup_ctx.append(manage_connection)
app.on_startup.append(load_configuration)

app.add_routes([
    web.get('/products/{merchant}', stream),
])

web.run_app(app)
