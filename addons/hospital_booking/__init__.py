from . import models


def _post_init_hook(env):
    from .hooks import post_init_hook
    post_init_hook(env)
