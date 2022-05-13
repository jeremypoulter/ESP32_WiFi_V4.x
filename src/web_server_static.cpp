#if defined(ENABLE_DEBUG) && !defined(ENABLE_DEBUG_WEB_STATIC)
#undef ENABLE_DEBUG
#endif

#include <Arduino.h>

#include "emonesp.h"
#include "web_server.h"
#include "web_server_static.h"
#include "app_config.h"
#include "net_manager.h"

extern bool enableCors; // defined in web_server.cpp

#include "web_static/web_server_static_files.h"

#define ARRAY_LENGTH(x) (sizeof(x)/sizeof((x)[0]))

#define IS_ALIGNED(x)   (0 == ((uint32_t)(x) & 0x3))

// Pages
static const char _HOME_PAGE[] PROGMEM = "/home.html";
#define HOME_PAGE FPSTR(_HOME_PAGE)

static const char _WIFI_PAGE[] PROGMEM = "/wifi_portal.html";
#define WIFI_PAGE FPSTR(_WIFI_PAGE)

StaticFileWebHandler::StaticFileWebHandler()
{
}

bool StaticFileWebHandler::_getFile(AsyncWebServerRequest *request, StaticFile **file)
{
  // Remove the found uri
  String path = request->url();
  if(path == "/") {
    path = String(net_wifi_mode_is_ap_only() ? WIFI_PAGE : HOME_PAGE);
  }

  DBUGF("Looking for %s", path.c_str());

  for(int i = 0; i < ARRAY_LENGTH(staticFiles); i++) {
    if(path == staticFiles[i].filename)
    {
      DBUGF("Found %s %d@%p", staticFiles[i].filename, staticFiles[i].length, staticFiles[i].data);

      if(file) {
        *file = &staticFiles[i];
      }
      return true;
    }
  }

  return false;
}

bool StaticFileWebHandler::canHandle(AsyncWebServerRequest *request)
{
  StaticFile *file = NULL;
  if (request->method() == HTTP_GET &&
      _getFile(request, &file))
  {
    request->_tempObject = file;
    DBUGF("[StaticFileWebHandler::canHandle] TRUE");
    return true;
  }

  return false;
}

void StaticFileWebHandler::handleRequest(AsyncWebServerRequest *request)
{
  dumpRequest(request);

  // Are we authenticated
  if(!net_wifi_mode_is_ap_only() && www_username!="" &&
     false == request->authenticate(www_username.c_str(), www_password.c_str())) {
    request->requestAuthentication(esp_hostname.c_str());
    return;
  }

  StaticFile *file = (StaticFile *)request->_tempObject;
  if(file)
  {
    request->_tempObject = NULL;

    AsyncWebHeader *ifNoneMatch = request->getHeader(F("If-None-Match"));
    if(ifNoneMatch && ifNoneMatch->value().equals(file->etag))
    {
      AsyncWebServerResponse *response = request->beginResponse(304, file->type, "");
      response->addHeader(F("Cache-Control"), F("public, max-age=30, must-revalidate"));
      request->send(response);
      return;
    }

    AsyncWebServerResponse *response = request->beginResponse_P(200, file->type, (const uint8_t *)file->data, file->length);
    // response->addHeader("Content-Encoding", "gzip");
    response->addHeader("Connection","close");
    if (enableCors) {
      response->addHeader(F("Access-Control-Allow-Origin"), F("*"));
    }
    response->addHeader(F("Cache-Control"), F("public, max-age=30, must-revalidate"));
    response->addHeader(F("Etag"), file->etag);
    request->send(response);
  } else {
    request->send(404);
  }
}
