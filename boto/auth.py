# Copyright 2010 Google Inc.
#
# Permission is hereby granted, free of charge, to any person obtaining a
# copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish, dis-
# tribute, sublicense, and/or sell copies of the Software, and to permit
# persons to whom the Software is furnished to do so, subject to the fol-
# lowing conditions:
#
# The above copyright notice and this permission notice shall be included
# in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
# OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABIL-
# ITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT
# SHALL THE AUTHOR BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
# WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
# IN THE SOFTWARE.


"""
Handles authentication required to AWS and GS
"""

import base64
import boto
import boto.auth_handler
import boto.exception
import boto.plugin
import boto.utils
import hmac
import sys
import time
import urllib

from boto.auth_handler import AuthHandler
from boto.exception import BotoClientError
#
# the following is necessary because of the incompatibilities
# between Python 2.4, 2.5, and 2.6 as well as the fact that some
# people running 2.4 have installed hashlib as a separate module
# this fix was provided by boto user mccormix.
# see: http://code.google.com/p/boto/issues/detail?id=172
# for more details.
#
try:
    from hashlib import sha1 as sha
    from hashlib import sha256 as sha256

    if sys.version[:3] == "2.4":
        # we are using an hmac that expects a .new() method.
        class Faker:
            def __init__(self, which):
                self.which = which
                self.digest_size = self.which().digest_size

            def new(self, *args, **kwargs):
                return self.which(*args, **kwargs)

        sha = Faker(sha)
        sha256 = Faker(sha256)

except ImportError:
    import sha
    sha256 = None

class HmacKeys(object):
    """Key based Auth handler helper."""

    def __init__(self, host, config, provider):
        storage_keys = self._get_keys(config, provider)
        if not storage_keys:
            raise boto.auth_handler.NotReadyToAuthenticate()
        self._access_key, self._secret_key = storage_keys
        self._provider = provider
        self._hmac = hmac.new(self._secret_key, digestmod=sha)
        if sha256:
            self._hmac_256 = hmac.new(self._secret_key, digestmod=sha256)
        else:
            self._hmac_256 = None

    def _get_keys(self, config, provider):
        if (provider.name == 'aws' and
            config.has_option('Credentials', 'aws_secret_access_key')):
            secret_key = config.get('Credentials', 'aws_secret_access_key')
            access_key = config.get('Credentials', 'aws_access_key_id')
            return (access_key, secret_key)
        if (provider.name == 'google' and
            config.has_option('Credentials', 'gs_secret_access_key')):
            secret_key = config.get('Credentials', 'gs_secret_access_key')
            access_key = config.get('Credentials', 'gs_access_key_id')
            return (access_key, secret_key)
        return None

class HmacAuthHandler(AuthHandler, HmacKeys):
    """Class S3 key based Auth handler.

    Implements the AWS key based auth handling. The same works for gs too.
    """

    S3_ENDPOINT = 's3.amazonaws.com'
    GS_ENDPOINT = 'commondatastorage.googleapis.com'

    def __init__(self, host, config, provider):
        HmacKeys.__init__(self, host, config, provider)
        if (host.endswith(self.S3_ENDPOINT) or
            host.endswith(self.GS_ENDPOINT)):
            return
        raise boto.auth_handler.NotReadyToAuthenticate()

    def _get_bucket(self, http_request):
        i = http_request.host.find('.' + self.S3_ENDPOINT)
        if i != -1:
            return '/' + http_request.host[:i]
        i = http_request.host.find('.' + self.GS_ENDPOINT)
        if i != -1:
            return '/' + http_request.host[:i]
        return ''

    def add_auth(self, http_request):
        headers = http_request.headers
        method = http_request.method
        auth_path = '%s%s' % (self._get_bucket(http_request), http_request.path)
        if not headers.has_key('Date'):
            headers['Date'] = time.strftime("%a, %d %b %Y %H:%M:%S GMT",
                                            time.gmtime())

        c_string = boto.utils.canonical_string(method, auth_path, headers,
                                               None, self._provider)
        boto.log.debug('Canonical: %s' % c_string)
        hmac = self._hmac.copy()
        hmac.update(c_string)
        b64_hmac = base64.encodestring(hmac.digest()).strip()
        auth_hdr = self._provider.auth_header
        headers['Authorization'] = ("%s %s:%s" %
                                    (auth_hdr,
                                     self._access_key, b64_hmac))

class QuerySignatureHelper(HmacKeys):
    """Helper for Query signature based Auth handler.

    Concrete sub class need to implement _calc_sigature method.
    """

    def __init__(self, host, config, provider):
        HmacKeys.__init__(self, host, config, provider)
        if not host.endswith('.amazonaws.com'):
            # QuerySignature only works for amazon services.
            raise boto.auth_handler.NotReadyToAuthenticate()
        if host.endswith('s3.amazonaws.com'):
            # QuerySignature does not work with s3. s3 uses Authorization
            # header implemented using HmacAuthHandler. Everything else in
            # AWS supports query string authentication mechanism.
            raise boto.auth_handler.NotReadyToAuthenticate()

    def add_auth(self, http_request):
        server_name = self._server_name(http_request.host, http_request.port)
        headers = http_request.headers
        params = http_request.params
        params['AWSAccessKeyId'] = self._access_key
        params['SignatureVersion'] = self.SignatureVersion
        params['Timestamp'] = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
        qs, signature = self._calc_signature(
            http_request.params, http_request.method,
            http_request.path, server_name)
        boto.log.debug('query_string: %s Signature: %s' % (qs, signature))
        if http_request.method == 'POST':
            headers['Content-Type'] = 'application/x-www-form-urlencoded; charset=UTF-8'
            http_request.body = qs + '&Signature=' + urllib.quote(signature)
        else:
            http_request.body = ''
            http_request.path = (http_request.path + '?' + qs + '&Signature=' + urllib.quote(signature))
        # Now that query params are part of the path, clear the 'params' field
        # in request.
        http_request.params = {}

    def _server_name(self, host, port):
        if port == 80:
            signature_host = host
        else:
            # This unfortunate little hack can be attributed to
            # a difference in the 2.6 version of httplib.  In old
            # versions, it would append ":443" to the hostname sent
            # in the Host header and so we needed to make sure we
            # did the same when calculating the V2 signature.  In 2.6
            # (and higher!)
            # it no longer does that.  Hence, this kludge.
            if sys.version[:3] in ('2.6', '2.7') and port == 443:
                signature_host = host
            else:
                signature_host = '%s:%d' % (host, port)
        return signature_host

class QuerySignatureV0AuthHandler(QuerySignatureHelper, AuthHandler):
    """Class SQS query signature based Auth handler."""

    SignatureVersion = 0
    capability = ['sign-v0']

    def _calc_signature(self, params, *args):
        boto.log.debug('using _calc_signature_0')
        hmac = self._hmac.copy()
        s = params['Action'] + params['Timestamp']
        hmac.update(s)
        keys = params.keys()
        keys.sort(cmp = lambda x, y: cmp(x.lower(), y.lower()))
        pairs = []
        for key in keys:
            val = bot.utils.get_utf8_value(params[key])
            pairs.append(key + '=' + urllib.quote(val))
        qs = '&'.join(pairs)
        return (qs, base64.b64encode(hmac.digest()))

class QuerySignatureV1AuthHandler(QuerySignatureHelper, AuthHandler):
    """Class SQS query signature based Auth handler."""

    SignatureVersion = 1
    capability = ['sign-v1']

    def _calc_signature(self, params, *args):
        boto.log.debug('using _calc_signature_1')
        hmac = self._hmac.copy()
        keys = params.keys()
        keys.sort(cmp = lambda x, y: cmp(x.lower(), y.lower()))
        pairs = []
        for key in keys:
            hmac.update(key)
            val = boto.utils.get_utf8_value(params[key])
            hmac.update(val)
            pairs.append(key + '=' + urllib.quote(val))
        qs = '&'.join(pairs)
        return (qs, base64.b64encode(hmac.digest()))

class QuerySignatureV2AuthHandler(QuerySignatureHelper, AuthHandler):
    """Class SQS query signature based Auth handler."""

    SignatureVersion = 2
    capability = ['sign-v2']

    def _calc_signature(self, params, verb, path, server_name):
        boto.log.debug('using _calc_signature_2')
        string_to_sign = '%s\n%s\n%s\n' % (verb, server_name.lower(), path)
        if self._hmac_256:
            hmac = self._hmac_256.copy()
            params['SignatureMethod'] = 'HmacSHA256'
        else:
            hmac = self._hmac.copy()
            params['SignatureMethod'] = 'HmacSHA1'
        keys = params.keys()
        keys.sort()
        pairs = []
        for key in keys:
            val = boto.utils.get_utf8_value(params[key])
            pairs.append(urllib.quote(key, safe='') + '=' +
                         urllib.quote(val, safe='-_~'))
        qs = '&'.join(pairs)
        boto.log.debug('query string: %s' % qs)
        string_to_sign += qs
        boto.log.debug('string_to_sign: %s' % string_to_sign)
        hmac.update(string_to_sign)
        b64 = base64.b64encode(hmac.digest())
        boto.log.debug('len(b64)=%d' % len(b64))
        boto.log.debug('base64 encoded digest: %s' % b64)
        return (qs, b64)


def get_auth_handler(host, config, provider, requested_capability=None):
    """Finds an AuthHandler that is ready to authenticate.

    Lists through all the registered AuthHandlers to find one that is willing
    to handle for the given config and provider.

    :type host: string
    :param host:

    :type config:
    :param config:

    :type provider:
    :param provider:

    Returns:
        An implementation of AuthHandler.

    Raises:
        boto.exception.NoAuthHandlerFound:
        boto.exception.TooManyAuthHandlerReadyToAuthenticate:
    """
    ready_handlers = []
    auth_handlers = boto.plugin.get_plugin(AuthHandler, requested_capability)
    total_handlers = len(auth_handlers)
    for handler in auth_handlers:
        try:
            ready_handlers.append(handler(host, config, provider))
        except boto.auth_handler.NotReadyToAuthenticate:
            pass
 
    if not ready_handlers:
        checked_handlers = auth_handlers
        names = [handler.__name__ for handler in checked_handlers]
        raise boto.exception.NoAuthHandlerFound(
              'No handler was ready to authenticate. %d handlers were checked.'
              ' %s ' % (len(names), str(names)))

    if len(ready_handlers) > 1:
        # NOTE: Even though it would be nice to accept more than one handler
        # by using one of the many ready handlers, we are never sure that each
        # of them are referring to the same storage account. Since we cannot
        # easily guarantee that, it is always safe to fail, rather than operate
        # on the wrong account.
        names = [handler.__class__.__name__ for handler in ready_handlers]
        raise boto.exception.TooManyAuthHandlerReadyToAuthenticate(
               '%d AuthHandlers ready to authenticate, '
               'only 1 expected: %s' % (len(names), str(names)))

    return ready_handlers[0]
