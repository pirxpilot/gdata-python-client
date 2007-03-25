#!/usr/bin/python
#
# Copyright (C) 2006 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


"""GDataService provides CRUD ops. and programmatic login for GData services.

  Error: A base exception class for all exceptions in the gdata_client
         module.

  CaptchaRequired: This exception is thrown when a login attempt results in a
                   captcha challenge from the ClientLogin service. When this
                   exception is thrown, the captcha_token and captcha_url are
                   set to the values provided in the server's response.

  BadAuthentication: Raised when a login attempt is made with an incorrect
                     username or password.

  NotAuthenticated: Raised if an operation requiring authentication is called
                    before a user has authenticated.

  NonAuthSubToken: Raised if a method to modify an AuthSub token is used when
                   the user is either not authenticated or is authenticated
                   through programmatic login.

  RequestError: Raised if a CRUD request returned a non-success code. 

  UnexpectedReturnType: Raised if the response from the server was not of the
                        desired type. For example, this would be raised if the
                        server sent a feed when the client requested an entry.

  GDataService: Encapsulates user credentials needed to perform insert, update
                and delete operations with the GData API. An instance can
                perform user authentication, query, insertion, deletion, and 
                update.

  Query: Eases query URI creation by allowing URI parameters to be set as 
         dictionary attributes. For example a query with a feed of 
         '/base/feeds/snippets' and ['bq'] set to 'digital camera' will 
         produce '/base/feeds/snippets?bq=digital+camera' when .ToUri() is 
         called on it.
"""

__author__ = 'api.jscudder (Jeffrey Scudder)'


import httplib
import urllib
from elementtree import ElementTree
import app_service
import gdata
import atom
import re


PROGRAMMATIC_AUTH_LABEL = 'GoogleLogin auth'
AUTHSUB_AUTH_LABEL = 'AuthSub token'


class Error(Exception):
  pass


class CaptchaRequired(Error):
  pass


class BadAuthentication(Error):
  pass


class NotAuthenticated(Error):
  pass


class NonAuthSubToken(Error):
  pass


class RequestError(Error):
  pass


class UnexpectedReturnType(Error):
  pass


class GDataService(app_service.AtomService):
  """Contains elements needed for GData login and CRUD request headers.

  Maintains additional headers (tokens for example) needed for the GData 
  services to allow a user to perform inserts, updates, and deletes.
  """

  def __init__(self, email=None, password=None, account_type='GOOGLE',
               service=None, source=None, server=None, 
               additional_headers=None):
    """Creates an object of type GDataClient.

    Args:
      email: string (optional) The user's email address, used for
             authentication.
      password: string (optional) The user's password.
      account_type: string (optional) The type of account to use. Use
              'GOOGLE' for regular Google accounts or 'HOSTED' for Google
              Apps accounts. Default value: 'GOOGLE'.
      service: string (optional) The desired service for which credentials
               will be obtained.
      source: string (optional) The name of the user's application.
      server: string (optional) The name of the server to which a connection
              will be opened. Default value: 'base.google.com'.
      additional_headers: dictionary (optional) Any additional headers which 
                          should be included with CRUD operations.
    """

    self.email = email
    self.password = password
    self.account_type = account_type
    self.service = service
    self.source =  source
    self.server = server
    self.additional_headers = additional_headers or {}
    self.__auth_token = None
    self.__auth_type = None
    self.__captcha_token = None
    self.__captcha_url = None
    self.__gsessionid = None
 
  # Define properties for GDataClient
  def _SetAuthSubToken(self, auth_token):
    """Sets the token sent in requests to an AuthSub token.

    Only use this method if you have received a token from the AuthSub 
    service. The auth_token is set automatically when ProgrammaticLogin()
    is used. See documentation for Google AuthSub here:
    http://code.google.com/apis/accounts/AuthForWebApps.html .

    Args:
      auth_token: string The token returned by the AuthSub service.
    """

    self.__auth_token = auth_token
    # The auth token is only set externally when using AuthSub authentication,
    # so set the auth_type to indicate AuthSub.
    self.__auth_type = AUTHSUB_AUTH_LABEL

  def __SetAuthSubToken(self, auth_token):
    self._SetAuthSubToken(auth_token)

  def _GetAuthToken(self):
    """Returns the auth token used for authenticating requests.

    Returns:
      string
    """

    return self.__auth_token

  def __GetAuthToken(self):
    return self._GetAuthToken()

  auth_token = property(__GetAuthToken, __SetAuthSubToken,
      doc="""Get or set the token used for authentication.""")

  def _GetCaptchaToken(self):
    """Returns a captcha token if the most recent login attempt generated one.

    The captcha token is only set if the Programmatic Login attempt failed 
    because the Google service issued a captcha challenge.

    Returns:
      string
    """

    return self.__captcha_token

  def __GetCaptchaToken(self):
    return self._GetCaptchaToken()

  captcha_token = property(__GetCaptchaToken,
      doc="""Get the captcha token for a login request.""")

  def _GetCaptchaURL(self):
    """Returns the URL of the captcha image if a login attempt generated one.
     
    The captcha URL is only set if the Programmatic Login attempt failed
    because the Google service issued a captcha challenge.

    Returns:
      string
    """

    return self.__captcha_url

  def __GetCaptchaURL(self):
    return self._GetCaptchaURL()

  captcha_url = property(__GetCaptchaURL,
      doc="""Get the captcha URL for a login request.""")

  # Authentication operations

  def ProgrammaticLogin(self, captcha_token=None, captcha_response=None):
    """Authenticates the user and sets the GData Auth token.

    Login retreives a temporary auth token which must be used with all
    requests to GData services. The auth token is stored in the GData client
    object.

    Login is also used to respond to a captcha challenge. If the user's login
    attempt failed with a CaptchaRequired error, the user can respond by
    calling Login with the captcha token and the answer to the challenge.

    Args:
      captcha_token: string (optional) The identifier for the captcha challenge
                     which was presented to the user.
      captcha_response: string (optional) The user's answer to the captch 
                        challenge.

    Raises:
      CaptchaRequired if the login service will require a captcha response
      BadAuthentication if the login service rejected the username or password
      Error if the login service responded with a 403 different from the above
    """

    # Create a POST body containing the user's credentials.
    if captcha_token and captcha_response:
      # Send the captcha token and response as part of the POST body if the
      # user is responding to a captch challenge.
      request_body = urllib.urlencode({'Email': self.email,
                                       'Passwd': self.password,
                                       'accountType': self.account_type,
                                       'service': self.service,
                                       'source': self.source,
                                       'logintoken': captcha_token,
                                       'logincaptcha': captcha_response})
    else:
      request_body = urllib.urlencode({'Email': self.email,
                                       'Passwd': self.password,
                                       'accountType': self.account_type,
                                       'service': self.service,
                                       'source': self.source})

    # Open a connection to the authentication server.
    auth_connection = httplib.HTTPSConnection('www.google.com')

    # Begin the POST request to the client login service.
    auth_connection.putrequest('POST', '/accounts/ClientLogin')
    # Set the required headers for an Account Authentication request.
    auth_connection.putheader('Content-type',
                              'application/x-www-form-urlencoded')
    auth_connection.putheader('Content-Length',str(len(request_body)))
    auth_connection.endheaders()

    auth_connection.send(request_body)

    # Process the response and throw exceptions if the login request did not
    # succeed.
    auth_response = auth_connection.getresponse()

    if auth_response.status == 200:
      response_body = auth_response.read()
      for response_line in response_body.splitlines():
        if response_line.startswith('Auth='):
          self.__auth_token = response_line.lstrip('Auth=')
          self.__auth_type = PROGRAMMATIC_AUTH_LABEL
          # Get rid of any residual captcha information because the request
          # succeeded.
          self.__captcha_token = None
          self.__captcha_url = None

    elif auth_response.status == 403:
      response_body = auth_response.read()
      # Examine each line to find the error type and the captcha token and
      # captch URL if they are present.
      for response_line in response_body.splitlines():
        if response_line.startswith('Error='):
          error_line = response_line
        elif response_line.startswith('CaptchaToken='):
          self.__captcha_token = response_line.lstrip('CaptchaToken=')
        elif response_line.startswith('CaptchaUrl='):
          self.__captcha_url = 'https://www.google.com/accounts/Captcha%s' % (
                               response_line.lstrip('CaptchaUrl='))
      

      # Raise an exception based on the error type in the 403 response.
      # In cases where there was no captcha challenge, remove any previous
      # captcha values.
      if error_line == 'Error=CaptchaRequired':
        raise CaptchaRequired, 'Captcha Required'
      elif error_line == 'Error=BadAuthentication':
        self.__captcha_token = None
        self.__captcha_url = None
        raise BadAuthentication, 'Incorrect username or password'
      else:
        self.__captcha_token = None
        self.__captcha_url = None
        raise Error, 'Server responded with a 403 code'

  def GenerateAuthSubURL(self, next, scope, secure=False, session=True):
    """Generate a URL at which the user will login and be redirected back.

    Users enter their credentials on a Google login page and a token is sent
    to the URL specified in next. See documentation for AuthSub login at:
    http://code.google.com/apis/accounts/AuthForWebApps.html

    Args:
      next: string The URL user will be sent to after logging in.
      scope: string The URL of the service to be accessed.
      secure: boolean (optional) Determines whether or not the issued token
              is a secure token.
      session: boolean (optional) Determines whether or not the issued token
               can be upgraded to a session token.
    """

    # Translate True/False values for parameters into numeric values acceoted
    # by the AuthSub service.
    if secure:
      secure = 1
    else:
      secure = 0

    if session:
      session = 1
    else:
      session = 0

    request_params = urllib.urlencode({'next': next, 'scope': scope,
                                    'secure': secure, 'session': session})
    return 'https://www.google.com/accounts/AuthSubRequest?%s' % request_params

  def UpgradeToSessionToken(self):
    """Upgrades a single use AuthSub token to a session token.

    Raises:
      NonAuthSubToken if the user's auth token is not an AuthSub token
    """
    
    if self.__auth_type != AUTHSUB_AUTH_LABEL: 
      raise NonAuthSubToken

    upgrade_connection = httplib.HTTPSConnection('www.google.com')
    upgrade_connection.putrequest('GET', '/accounts/AuthSubSessionToken')
    
    upgrade_connection.putheader('Content-Type',
                                 'application/x-www-form-urlencoded')
    upgrade_connection.putheader('Authorization', '%s=%s' %
        (self.__auth_type, self.__auth_token))
    upgrade_connection.endheaders()

    response = upgrade_connection.getresponse()

    response_body = response.read()
    if response.status == 200:
      for response_line in response_body.splitlines():
        if response_line.startswith('Token='):
          self.__auth_token = response_line.lstrip('Token=')

  def RevokeAuthSubToken(self):
    """Revokes an existing AuthSub token.

    Raises:
      NonAuthSubToken if the user's auth token is not an AuthSub token
    """

    if self.__auth_type != AUTHSUB_AUTH_LABEL:
      raise NonAuthSubToken
    
    revoke_connection = httplib.HTTPSConnection('www.google.com')
    revoke_connection.putrequest('GET', '/accounts/AuthSubRevokeToken')
    
    revoke_connection.putheader('Content-Type', 
                                'application/x-www-form-urlencoded')
    revoke_connection.putheader('Authorization', '%s=%s' %
            (self.__auth_type, self.__auth_token))
    revoke_connection.endheaders()

    response = revoke_connection.getresponse()
    if response.status == 200:
      self.__auth_type = None
      self.__auth_token = None

  # CRUD operations
  def Get(self, uri, extra_headers=None, redirects_remaining=4):
    """Query the GData API with the given URI

    The uri is the portion of the URI after the server value 
    (ex: www.google.com).

    To perform a query against Google Base, set the server to 
    'base.google.com' and set the uri to '/base/feeds/...', where ... is 
    your query. For example, to find snippets for all digital cameras uri 
    should be set to: '/base/feeds/snippets?bq=digital+camera'

    Args:
      uri: string The query in the form of a URI. Example:
           '/base/feeds/snippets?bq=digital+camera'.
      extra_headers: dictionary (optional) Extra HTTP headers to be included
                     in the GET request. These headers are in addition to 
                     those stored in the client's additional_headers property.
                     The client automatically sets the Content-Type and 
                     Authorization headers.

    Returns:
      A GDataFeed or Entry depending on which is sent from the server.
    """
    if extra_headers is None:
      extra_headers = {}

    # Add the authentication header to the Get request
    if self.__auth_token:
      extra_headers['Authorization'] = '%s=%s' % (self.__auth_type, 
                                                  self.__auth_token)

    if self.__gsessionid is not None:
      if uri.find('gsessionid=') < 0:
        if uri.find('?') > -1:
          uri += '&gsessionid=%s' % (self.__gsessionid,)
        else:
          uri += '?gsessionid=%s' % (self.__gsessionid,)

    server_response = app_service.AtomService.Get(self, uri, extra_headers)
    result_body = server_response.read()

    if server_response.status == 200:
      feed = gdata.GDataFeedFromString(result_body)
      if not feed:
        entry = atom.EntryFromString(result_body)
        if not entry:
          return result_body
        return entry
      return feed
    elif server_response.status == 302:
      if redirects_remaining > 0:
        location = server_response.getheader('Location')
        if location is not None:
          m = re.compile('[\?\&]gsessionid=(\w*)').search(location)
          if m is not None:
            self.__gsessionid = m.group(1)
          return self.Get(location, extra_headers, redirects_remaining - 1)
        else:
          raise RequestError, {'status': server_response.status,
              'reason': '302 received without Location header',
              'body': result_body}
      else:
        raise RequestError, {'status': server_response.status,
            'reason': 'Redirect received, but redirects_remaining <= 0',
            'body': result_body}
    else:
      raise RequestError, {'status': server_response.status,
          'reason': server_response.reason, 'body': result_body}

  def GetEntry(self, uri, extra_headers=None):
    """Query the GData API with the given URI and receive an Entry.
    
    See also documentation for gdata_service.Get

    Args:
      uri: string The query in the form of a URI. Example:
           '/base/feeds/snippets?bq=digital+camera'.
      extra_headers: dictionary (optional) Extra HTTP headers to be included
                     in the GET request. These headers are in addition to
                     those stored in the client's additional_headers property.
                     The client automatically sets the Content-Type and
                     Authorization headers.

    Returns:
      A GDataEntry built from the XML in the server's response.
    """

    result = self.Get(uri, extra_headers)
    if isinstance(result, atom.Entry):
      return result
    else:
      raise UnexpectedReturnType, 'Server did not send an entry' 

  def GetFeed(self, uri, extra_headers=None):
    """Query the GData API with the given URI and receive a Feed.

    See also documentation for gdata_service.Get

    Args:
      uri: string The query in the form of a URI. Example:
           '/base/feeds/snippets?bq=digital+camera'.
      extra_headers: dictionary (optional) Extra HTTP headers to be included
                     in the GET request. These headers are in addition to
                     those stored in the client's additional_headers property.
                     The client automatically sets the Content-Type and
                     Authorization headers.

    Returns:
      A GDataFeed built from the XML in the server's response.
    """

    result = self.Get(uri, extra_headers)
    if isinstance(result, atom.Feed):
      return result
    else:
      raise UnexpectedReturnType, 'Server did not send a feed'  

  def Post(self, data, uri, extra_headers=None, url_params=None, 
           escape_params=True, redirects_remaining=4):
    """Insert data into a GData service at the given URI.

    Args:
      data: string, ElementTree._Element, atom.Entry, or gdata.GDataEntry The
            XML to be sent to the uri. 
      uri: string The location (feed) to which the data should be inserted. 
           Example: '/base/feeds/items'. 
      extra_headers: dict (optional) HTTP headers which are to be included. 
                     The client automatically sets the Content-Type,
                     Authorization, and Content-Length headers.
      url_params: dict (optional) Additional URL parameters to be included
                  in the URI. These are translated into query arguments
                  in the form '&dict_key=value&...'.
                  Example: {'max-results': '250'} becomes &max-results=250
      escape_params: boolean (optional) If false, the calling code has already
                     ensured that the query will form a valid URL (all
                     reserved characters have been escaped). If true, this
                     method will escape the query and any URL parameters
                     provided.

    Returns:
      httplib.HTTPResponse Server's response to the POST request.
    """
    if extra_headers is None:
      extra_headers = {}

    # Add the authentication header to the Get request
    if self.__auth_token:
      extra_headers['Authorization'] = '%s=%s' % (self.__auth_type, 
                                                  self.__auth_token)

    if self.__gsessionid is not None:
      if uri.find('gsessionid=') < 0:
        if uri.find('?') > -1:
          uri += '&gsessionid=%s' % (self.__gsessionid,)
        else:
          uri += '?gsessionid=%s' % (self.__gsessionid,)
                                                  
    server_response = app_service.AtomService.Post(self, data, uri,
        extra_headers, url_params, escape_params)
    result_body = server_response.read()

    if server_response.status == 201:
      feed = gdata.GDataFeedFromString(result_body)
      if not feed:
        entry = atom.EntryFromString(result_body)
        if not entry:
          return result_body
        return entry
      return feed
    elif server_response.status == 302:
      if redirects_remaining > 0:
        location = server_response.getheader('Location')
        if location is not None:
          m = re.compile('[\?\&]gsessionid=(\w*)').search(location)
          if m is not None:
            self.__gsessionid = m.group(1) 
          return self.Post(data, location, extra_headers, url_params, escape_params, redirects_remaining - 1)
        else:
          raise RequestError, {'status': server_response.status,
              'reason': '302 received without Location header',
              'body': result_body}
      else:
        raise RequestError, {'status': server_response.status,
            'reason': 'Redirect received, but redirects_remaining <= 0',
            'body': result_body}
    else:
      raise RequestError, {'status': server_response.status,
          'reason': server_response.reason, 'body': result_body}

  def Put(self, data, uri, extra_headers=None, url_params=None, 
          escape_params=True, redirects_remaining=3):
    """Updates an entry at the given URI.
     
    Args:
      data: string, ElementTree._Element, or xml_wrapper.ElementWrapper The 
            XML containing the updated data.
      uri: string A URI indicating entry to which the update will be applied.
           Example: '/base/feeds/items/ITEM-ID'
      extra_headers: dict (optional) HTTP headers which are to be included.
                     The client automatically sets the Content-Type,
                     Authorization, and Content-Length headers.
      url_params: dict (optional) Additional URL parameters to be included
                  in the URI. These are translated into query arguments
                  in the form '&dict_key=value&...'.
                  Example: {'max-results': '250'} becomes &max-results=250
      escape_params: boolean (optional) If false, the calling code has already
                     ensured that the query will form a valid URL (all
                     reserved characters have been escaped). If true, this
                     method will escape the query and any URL parameters
                     provided.
  
    Returns:
      httplib.HTTPResponse Server's response to the PUT request.
    """
    if extra_headers is None:
      extra_headers = {}

    # Add the authentication header to the Get request
    if self.__auth_token:
      extra_headers['Authorization'] = '%s=%s' % (self.__auth_type, 
                                                  self.__auth_token)

    if self.__gsessionid is not None:
      if uri.find('gsessionid=') < 0:
        if uri.find('?') > -1:
          uri += '&gsessionid=%s' % (self.__gsessionid,)
        else:
          uri += '?gsessionid=%s' % (self.__gsessionid,)
                                                  
    server_response = app_service.AtomService.Put(self, data, uri,
        extra_headers, url_params, escape_params)
    result_body = server_response.read()

    if server_response.status == 200:
      feed = gdata.GDataFeedFromString(result_body)
      if not feed:
        entry = atom.EntryFromString(result_body)
        if not entry:
          return result_body
        return entry
      return feed
    elif server_response.status == 302:
      if redirects_remaining > 0:
        location = server_response.getheader('Location')
        if location is not None:
          m = re.compile('[\?\&]gsessionid=(\w*)').search(location)
          if m is not None:
            self.__gsessionid = m.group(1) 
          return self.Put(data, location, extra_headers, url_params, escape_params, redirects_remaining - 1)
        else:
          raise RequestError, {'status': server_response.status,
              'reason': '302 received without Location header',
              'body': result_body}
      else:
        raise RequestError, {'status': server_response.status,
            'reason': 'Redirect received, but redirects_remaining <= 0',
            'body': result_body}
    else:
      raise RequestError, {'status': server_response.status,
          'reason': server_response.reason, 'body': result_body}

  def Delete(self, uri, extra_headers=None, url_params=None, 
             escape_params=True, redirects_remaining=4):
    """Deletes the entry at the given URI.

    Args:
      uri: string The URI of the entry to be deleted. Example: 
           '/base/feeds/items/ITEM-ID'
      extra_headers: dict (optional) HTTP headers which are to be included.
                     The client automatically sets the Content-Type and
                     Authorization headers.
      url_params: dict (optional) Additional URL parameters to be included
                  in the URI. These are translated into query arguments
                  in the form '&dict_key=value&...'.
                  Example: {'max-results': '250'} becomes &max-results=250
      escape_params: boolean (optional) If false, the calling code has already
                     ensured that the query will form a valid URL (all
                     reserved characters have been escaped). If true, this
                     method will escape the query and any URL parameters
                     provided.

    Returns:
      True if the entry was deleted.
    """
    if extra_headers is None:
      extra_headers = {}

    # Add the authentication header to the Get request
    if self.__auth_token:
      extra_headers['Authorization'] = '%s=%s' % (self.__auth_type, 
                                                  self.__auth_token)

    if self.__gsessionid is not None:
      if uri.find('gsessionid=') < 0:
        if uri.find('?') > -1:
          uri += '&gsessionid=%s' % (self.__gsessionid,)
        else:
          uri += '?gsessionid=%s' % (self.__gsessionid,)
                                                  
    server_response = app_service.AtomService.Delete(self, uri,
        extra_headers, url_params, escape_params)
    result_body = server_response.read()

    if server_response.status == 200:
      return True
    elif server_response.status == 302:
      if redirects_remaining > 0:
        location = server_response.getheader('Location')
        if location is not None:
          m = re.compile('[\?\&]gsessionid=(\w*)').search(location)
          if m is not None:
            self.__gsessionid = m.group(1) 
          return self.Delete(location, extra_headers, url_params, escape_params, redirects_remaining - 1)
        else:
          raise RequestError, {'status': server_response.status,
              'reason': '302 received without Location header',
              'body': result_body}
      else:
        raise RequestError, {'status': server_response.status,
            'reason': 'Redirect received, but redirects_remaining <= 0',
            'body': result_body}
    else:
      raise RequestError, {'status': server_response.status,
          'reason': server_response.reason, 'body': result_body}


class Query(dict):
  """Constructs a query URL to be used in GET requests
  
  Url parameters are created by adding key-value pairs to this object as a 
  dict. For example, to add &max-results=25 to the URL do
  my_query['max-results'] = 25

  Category queries are created by adding category strings to the categories
  member. All items in the categories list will be concatenated with the /
  symbol (symbolizing a category x AND y restriction). If you would like to OR
  2 categories, append them as one string with a | between the categories. 
  For example, do query.categories.append('Fritz|Laurie') to create a query
  like this feed/-/Fritz%7CLaurie . This query will look for results in both
  categories.
  """

  def __init__(self, feed=None, text_query=None, params=None, 
      categories=None):
    """Constructor for Query
    
    Args:
      feed: str (optional) The path for the feed (Examples: 
          '/base/feeds/snippets' or 'calendar/feeds/jo@gmail.com/private/full'
      text_query: str (optional) The contents of the q query parameter. The
          contents of the text_query are URL escaped upon conversion to a URI.
      params: dict (optional) Parameter value string pairs which become URL
          params when translated to a URI. These parameters are added to the
          query's items (key-value pairs).
      categories: list (optional) List of category strings which should be
          included as query categories. See 
          http://code.google.com/apis/gdata/reference.html#Queries for 
          details. If you want to get results from category A or B (both 
          categories), specify a single list item 'A|B'. 
    """
    
    self.feed = feed
    self.categories = []
    if text_query:
      self.text_query = text_query
    if isinstance(params, dict):
      for param in params:
        self[param] = params[param]
    if isinstance(categories, list):
      for category in categories:
        self.categories.append(category)

  def _GetTextQuery(self):
    if 'q' in self.keys():
      return self['q']
    else:
      return None

  def _SetTextQuery(self, query):
    self['q'] = query

  text_query = property(_GetTextQuery, _SetTextQuery, 
      doc="""The feed query's q parameter""")

  def _GetAuthor(self):
    if 'author' in self.keys():
      return self['author']
    else:
      return None

  def _SetAuthor(self, query):
    self['author'] = query

  author = property(_GetAuthor, _SetAuthor,
      doc="""The feed query's author parameter""")

  def _GetAlt(self):
    if 'alt' in self.keys():
      return self['alt']
    else:
      return None

  def _SetAlt(self, query):
    self['alt'] = query

  alt = property(_GetAlt, _SetAlt,
      doc="""The feed query's alt parameter""")

  def _GetUpdatedMin(self):
    if 'updated-min' in self.keys():
      return self['updated-min']
    else:
      return None

  def _SetUpdatedMin(self, query):
    self['updated-min'] = query

  updated_min = property(_GetUpdatedMin, _SetUpdatedMin,
      doc="""The feed query's updated-min parameter""")

  def _GetUpdatedMax(self):
    if 'updated-max' in self.keys():
      return self['updated-max']
    else:
      return None

  def _SetUpdatedMax(self, query):
    self['updated-max'] = query

  updated_max = property(_GetUpdatedMax, _SetUpdatedMax,
      doc="""The feed query's updated-max parameter""")

  def _GetPublishedMin(self):
    if 'published-min' in self.keys():
      return self['published-min']
    else:
      return None

  def _SetPublishedMin(self, query):
    self['published-min'] = query

  published_min = property(_GetPublishedMin, _SetPublishedMin,
      doc="""The feed query's published-min parameter""")

  def _GetPublishedMax(self):
    if 'published-max' in self.keys():
      return self['published-max']
    else:
      return None

  def _SetPublishedMax(self, query):
    self['published-max'] = query

  published_max = property(_GetPublishedMax, _SetPublishedMax,
      doc="""The feed query's published-max parameter""")

  def _GetStartIndex(self):
    if 'start-index' in self.keys():
      return self['start-index']
    else:
      return None

  def _SetStartIndex(self, query):
    self['start-index'] = query

  start_index = property(_GetStartIndex, _SetStartIndex,
      doc="""The feed query's start-index parameter""")

  def _GetMaxResults(self):
    if 'max-results' in self.keys():
      return self['max-results']
    else:
      return None

  def _SetMaxResults(self, query):
    self['max-results'] = query

  max_results = property(_GetMaxResults, _SetMaxResults,
      doc="""The feed query's max-results parameter""")


  def ToUri(self):
    q_feed = self.feed or ''
    category_string = '/'.join(
        [urllib.quote_plus(c) for c in self.categories])
    # Add categories to the feed if there are any.
    if len(self.categories) > 0:
      q_feed = q_feed + '/-/' + category_string
    return app_service.BuildUri(q_feed, self)

  
