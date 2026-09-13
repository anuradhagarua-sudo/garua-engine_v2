[app]
title = Garua Engine
package.name = garuaalgo
package.domain = com.garua.v25
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,html,css,js
version = 25.8

requirements = python3==3.11.4,hostpython3==3.11.4,kivy==2.3.0,openssl,flask,markupsafe,werkzeug,jinja2,requests,urllib3,charset-normalizer,certifi,idna,websocket-client,pytz,python-dateutil,six,simplejson,kiteconnect,nest_asyncio

orientation = portrait
fullscreen = 0

android.permissions = INTERNET, ACCESS_NETWORK_STATE, WAKE_LOCK
android.api = 33
android.minapi = 24
android.ndk = 25b
android.archs = arm64-v8a

[buildozer]
log_level = 2
warn_on_root = 0
