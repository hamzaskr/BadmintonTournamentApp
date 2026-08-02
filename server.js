const http = require('http');
const fs = require('fs');
const path = require('path');

const rootDir = __dirname;
const dataDir = path.join(rootDir, 'data');
const dataFile = path.join(dataDir, 'duels.json');

function ensureDataFile() {
  if (!fs.existsSync(dataDir)) {
    fs.mkdirSync(dataDir, { recursive: true });
  }

  if (!fs.existsSync(dataFile)) {
    fs.writeFileSync(dataFile, '[]\n', 'utf8');
  }
}

function readDuels() {
  ensureDataFile();
  const raw = fs.readFileSync(dataFile, 'utf8');
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch (error) {
    return [];
  }
}

function writeDuels(duels) {
  ensureDataFile();
  fs.writeFileSync(dataFile, JSON.stringify(duels, null, 2) + '\n', 'utf8');
}

function sendJson(res, payload, statusCode = 200) {
  res.writeHead(statusCode, { 'Content-Type': 'application/json; charset=utf-8' });
  res.end(JSON.stringify(payload));
}

function contentTypeFor(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  switch (ext) {
    case '.html': return 'text/html; charset=utf-8';
    case '.css': return 'text/css; charset=utf-8';
    case '.js': return 'application/javascript; charset=utf-8';
    case '.json': return 'application/json; charset=utf-8';
    case '.png': return 'image/png';
    case '.jpg':
    case '.jpeg': return 'image/jpeg';
    case '.svg': return 'image/svg+xml';
    case '.ico': return 'image/x-icon';
    case '.webmanifest': return 'application/manifest+json';
    default: return 'application/octet-stream';
  }
}

function serveFile(res, filePath) {
  if (!fs.existsSync(filePath) || !fs.statSync(filePath).isFile()) {
    filePath = path.join(rootDir, 'index.html');
  }

  const stream = fs.createReadStream(filePath);
  res.writeHead(200, { 'Content-Type': contentTypeFor(filePath) });
  stream.pipe(res);
}

function parseJsonBody(req) {
  return new Promise((resolve, reject) => {
    let body = '';
    req.on('data', chunk => {
      body += chunk.toString();
    });
    req.on('end', () => {
      try {
        resolve(body ? JSON.parse(body) : {});
      } catch (error) {
        reject(error);
      }
    });
    req.on('error', reject);
  });
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host || 'localhost'}`);
  const pathname = decodeURIComponent(url.pathname);

  if (pathname === '/health') {
    sendJson(res, { status: 'ok' });
    return;
  }

  if (pathname === '/api/duels' && req.method === 'GET') {
    sendJson(res, { duels: readDuels() });
    return;
  }

  if (pathname === '/api/duels' && req.method === 'POST') {
    try {
      const record = await parseJsonBody(req);
      if (!record || typeof record !== 'object') {
        sendJson(res, { error: 'Invalid payload.' }, 400);
        return;
      }

      const player1 = String(record.player1 || '').trim();
      const player2 = String(record.player2 || '').trim();
      const score1 = Number(record.score1);
      const score2 = Number(record.score2);
      const maxPoints = Number(record.maxPoints);

      if (!player1 || !player2) {
        sendJson(res, { error: 'Both player names are required.' }, 400);
        return;
      }

      if (player1.toLowerCase() === player2.toLowerCase()) {
        sendJson(res, { error: 'Players must have unique names.' }, 400);
        return;
      }

      if (!Number.isFinite(score1) || !Number.isFinite(score2)) {
        sendJson(res, { error: 'Scores must be numeric.' }, 400);
        return;
      }

      const normalizedRecord = {
        id: record.id || `duel_${Date.now()}`,
        player1,
        player2,
        score1: Math.min(Math.max(Math.round(score1), 0), Number.isFinite(maxPoints) ? Math.max(1, Math.round(maxPoints)) : 99999),
        score2: Math.min(Math.max(Math.round(score2), 0), Number.isFinite(maxPoints) ? Math.max(1, Math.round(maxPoints)) : 99999),
        winner: record.winner || null,
        maxPoints: Number.isFinite(maxPoints) ? Math.max(1, Math.round(maxPoints)) : 11,
        createdAt: record.createdAt || new Date().toISOString(),
        resultSummary: record.resultSummary || `${player1} vs ${player2}`
      };

      const duels = readDuels();
      duels.unshift(normalizedRecord);
      writeDuels(duels.slice(0, 12));
      sendJson(res, { duel: normalizedRecord, duels: readDuels() });
    } catch (error) {
      sendJson(res, { error: 'Invalid JSON body.' }, 400);
    }
    return;
  }

  const sanitizedPath = pathname === '/' ? 'index.html' : pathname.replace(/^\/+/, '');
  const requestedPath = path.join(rootDir, sanitizedPath);
  const normalizedRoot = path.normalize(rootDir);
  const normalizedRequested = path.normalize(requestedPath);

  if (!normalizedRequested.startsWith(normalizedRoot + path.sep) && normalizedRequested !== normalizedRoot) {
    res.writeHead(403, { 'Content-Type': 'text/plain; charset=utf-8' });
    res.end('Forbidden');
    return;
  }

  serveFile(res, normalizedRequested);
});

ensureDataFile();

server.listen(3000, () => {
  console.log('Badminton tournament server listening on http://localhost:3000');
});
