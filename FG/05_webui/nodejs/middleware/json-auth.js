'use strict';

const { sessionFromToken } = require('../auth-store');
const { bearerToken } = require('../routes/auth-json');
const { safeTokenEqual } = require('../security');

module.exports = function jsonAuth(req, res, next) {
  const token = bearerToken(req);
  const metricsToken = String(process.env.METRICS_SERVICE_TOKEN || '');
  if (
    req.path === '/evaluation/metrics'
    && metricsToken.length >= 32
    && safeTokenEqual(token, metricsToken)
  ) {
    req.user = { role: 'service', isAdmin: true, scope: 'evaluation:metrics:read' };
    return next();
  }
  const session = sessionFromToken(token);
  if (!session) return res.status(401).json({ success: false, error: 'Authentication required.' });
  req.user = session.user;
  next();
};

module.exports.pioOnly = function pioOnly(req, res, next) {
  if (req.user?.role !== 'pio') {
    return res.status(403).json({ success: false, error: 'PIO mode is restricted to authorised PIO accounts.' });
  }
  next();
};
