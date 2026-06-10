import http.server, socketserver

ICS = (
    "BEGIN:VCALENDAR\r\n"
    "VERSION:2.0\r\n"
    "PRODID:-//AuditMock//EN\r\n"
    "X-WR-CALNAME:AuditMockFeed\r\n"
    "BEGIN:VEVENT\r\n"
    "UID:audit-tmp-mock-evt-1\r\n"
    "DTSTART:20260615T090000Z\r\n"
    "DTEND:20260615T100000Z\r\n"
    "SUMMARY:Audit Mock Feed Event\r\n"
    "END:VEVENT\r\n"
    "END:VCALENDAR\r\n"
)

class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass
    def do_GET(self):
        if self.path.startswith("/notics"):
            body = b"this is not an ical feed at all"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        body = ICS.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/calendar")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def do_PROPFIND(self):
        ml = (
            '<?xml version="1.0"?>'
            '<d:multistatus xmlns:d="DAV:"><d:response>'
            '<d:href>/dav/</d:href><d:propstat><d:prop>'
            '<d:resourcetype><d:collection/></d:resourcetype>'
            '</d:prop><d:status>HTTP/1.1 200 OK</d:status>'
            '</d:propstat></d:response></d:multistatus>'
        ).encode("utf-8")
        self.send_response(207)
        self.send_header("Content-Type", "application/xml")
        self.send_header("Content-Length", str(len(ml)))
        self.end_headers()
        self.wfile.write(ml)

socketserver.TCPServer.allow_reuse_address = True
with socketserver.TCPServer(("127.0.0.1", 8731), H) as httpd:
    httpd.serve_forever()
