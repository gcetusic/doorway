from aiohttp import BasicAuth, hdrs, web

import functools


@web.middleware
class AbstractAuthenticationMiddleware(object):
    async def get_credentials(self, *args, **kwargs):
        raise NotImplementedError

    async def check_credentials(self, *args, **kwargs):
        raise NotImplementedError

    async def remember(self, *args, **kwargs):
        raise NotImplementedError

    async def authenticate(self, request, handler):
        credentials = await self.get_credentials(request)
        if credentials is not None:
            identity = await self.check_credentials(request, credentials)

            if not identity:
                return web.Response(
                    status=web.HTTPUnauthorized.status_code)

            await self.remember(request, identity)

            return await handler(request)

        else:
            return web.Response(
                status=web.HTTPUnauthorized.status_code)

    def required(self, handler):
        @functools.wraps(handler)
        async def wrapper(request):
            return await self.authenticate(request, handler)

        return wrapper

    async def __call__(self, request, handler):
        return await self.authenticate(request, handler)


@web.middleware
class AbstractAuthorizationMiddleware(object):
    async def get_identity(self, request):
        raise NotImplementedError

    async def check_permission(self, request, identity, permission):
        raise NotImplementedError

    async def authorize(self, request, handler):
        identity = await self.get_identity(request)
        if (identity is not None
                and await self.check_permission(request, identity, 'read')):

            return await handler(request)

        else:
            return web.Response(
                status=web.HTTPForbidden.status_code)

    def required(self, handler):
        @functools.wraps(handler)
        async def wrapper(request):
            return await self.authorize(request, handler)

        return wrapper

    async def __call__(self, request, handler):
        return await self.authorize(request, handler)


class BasicAuthMiddleware(AbstractAuthenticationMiddleware):
    async def get_credentials(self, request):
        auth_header = request.headers.get(hdrs.AUTHORIZATION)
        if not auth_header:
            return None
        try:
            auth = BasicAuth.decode(auth_header=auth_header)
        except ValueError:
            auth = None
        return auth

    async def check_credentials(self, request, credentials):
        async with request.app['db'].acquire() as conn:
            ret = await conn.execute(
                "SELECT * FROM users WHERE username='{username}'".format(
                    username=credentials.login
                )
            )
            user = await ret.fetchone()
            if user is not None and user.passwd == credentials.password:
                return str(user.id)

        return False

    async def remember(self, request, identity):
        request['user_id'] = identity


class RequestAuthorizationMiddleware(AbstractAuthorizationMiddleware):
    async def get_identity(self, request):
        return request.get('user_id')

    async def check_permission(self, request, identity, permission):
        merchant = request.match_info.get('merchant')
        channel = request.rel_url.query['channel']

        identity = await self.get_identity(request)

        return identity in request.app['configuration']['routes'][f"{merchant}:{channel}"]['users']
