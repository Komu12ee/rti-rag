'use strict';
const { verifyToken } = require('../utils/security');

/**
 * Authentication middleware
 * Checks for active session cookie (chips_rag_session)
 * If not authenticated, redirects to home or returns 401
 */
module.exports = (req, res, next) => {
    // Check if user has an active session
    const session = verifyToken(req.cookies?.chips_rag_session, 'session');
    if (session) {
        req.user = { email: session.email };
        // User is authenticated, continue
        return next();
    }

    // User is not authenticated
    // If they're requesting JSON (API), return 401
    if (req.accepts('json')) {
        return res.status(401).json({ success: false, error: 'Unauthorized' });
    }

    // Otherwise redirect to home
    res.redirect('/');
};
