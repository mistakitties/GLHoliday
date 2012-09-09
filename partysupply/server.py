import os
import sys
import logging
import time
import ujson as json

import tornado
import tornado.ioloop
import tornado.web
import tornado.options
from tornado.curl_httpclient import CurlAsyncHTTPClient

from instagram import client, subscriptions

from models import process_update, Subscription, Media
from insta import INSTAGRAM_CLIENT_SECRET
import config

logger = logging.getLogger(__name__)


class BaseHandler(tornado.web.RequestHandler):
    pass


class IndexHandler(BaseHandler):

    def get(self):
        self.render("index.html")


class PostsHandler(BaseHandler):

    def get(self):
        tags = self.get_arguments("tags", [])
        min_created_time = self.get_argument("since", 0)
        
        for t in tags:
            Subscription.ensure_exists("tag", t)
        
        ids = Media.find_by_tag_and_created_time(tags[0], min_created_time)
        
        ret = dict(posts=ids, meta=dict(tags=tags))
        
        self.set_header("Content-Type", "application/json")
        self.write(json.dumps(ret))


class SubscriptionsHandler(BaseHandler):

    def get(self, obj, object_id):
        mode = self.get_argument("hub.mode")
        self.write(self.get_argument("hub.challenge"))
        logger.debug("Received acknowledgement for subscription: %s/%s", obj, object_id)

    def post(self, obj, object_id):
        self.object = obj
        self.object_id = object_id
        x_hub_signature = self.request.headers.get('X-Hub-Signature')
        raw_body = self.request.body
        try:
            logger.debug("Received updates for subscription: %s/%s", obj, object_id)
            self.application.reactor.process(INSTAGRAM_CLIENT_SECRET,
                                             raw_body,
                                             x_hub_signature)
        except subscriptions.SubscriptionVerifyError:
            logger.debug("Signature mismatch for subscription: %s/%s", obj, object_id)
        # I don't know why this is necessary...
        self.write("Thanks Instagram!")


class Application(tornado.web.Application):

    def __init__(self, routes, **settings):
        tornado.web.Application.__init__(self, routes, **settings)
        self.reactor = subscriptions.SubscriptionsReactor()
        self.reactor.register_callback(subscriptions.SubscriptionType.TAG,
                                       process_update)


def get_application(**kwargs):
    settings = dict(
        template_path=os.path.join(os.path.dirname(__file__), "templates"),
        static_path=os.path.join(os.path.dirname(__file__), "static"),
    )
    settings.update(kwargs)
    routes = [
        (r"^/$", IndexHandler),
        # (r"^/instagram/subscriptions", SubscriptionsHandler),
        (r"/posts", PostsHandler),
        (r"^/instagram/subscriptions/([a-z0-9_-]+)/([a-z0-9_-]+)", SubscriptionsHandler),
    ]
    return Application(routes, **settings)


def run_server(port=8080):
    tornado.options.parse_command_line()

    application = get_application(debug=config.DEBUG)
    application.listen(port, xheaders=True)
    logger.info("api started 0.0.0.0:%d [%s] %d", int(port), config.SG_ENV, os.getpid())
    tornado.ioloop.IOLoop.instance().start()
