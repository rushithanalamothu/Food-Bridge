// Loopback URLs for the isolated OIDC browser test inside the Docker test network.
// Not an application or production proxy.
import net from 'node:net';
for (const [port, host, target] of [[55173, 'web', 5173]]) {
  net
    .createServer((client) => {
      const upstream = net.connect(target, host);
      client.on('error', () => upstream.destroy());
      upstream.on('error', () => client.destroy());
      client.pipe(upstream).pipe(client);
    })
    .listen(port, '0.0.0.0');
}
