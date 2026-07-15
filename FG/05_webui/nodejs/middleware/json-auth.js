'use strict';

const { sessionFromToken } = require('../auth-store');
const { bearerToken } = require('../routes/auth-json');

module.exports = function jsonAuth(req, res, next) {
  const session = sessionFromToken(bearerToken(req));
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
