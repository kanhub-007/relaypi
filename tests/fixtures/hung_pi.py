"""A deliberately hung "PI": never reads stdin, sleeps forever.

Used to verify SubprocessStreamTransport.close() escalates from graceful close
to kill when the process won't exit within the shutdown timeout.
"""

import time

while True:
    time.sleep(3600)
