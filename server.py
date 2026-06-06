from http.server import HTTPServer
from handler import handler
import os

port = int(os.environ.get('PORT', 8000))
server = HTTPServer(('0.0.0.0', port), handler)
print(f'Starting server on port {port}')
server.serve_forever()