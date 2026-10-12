// License: GNU Lesser General Public License v3.0
// source (original): https://github.com/ajinabraham/njsscan/blob/master/tests/assets/node_source/true_positives/semantic_grep/jwt/jwt_not_revoked.js
// hash: e7a0a61
var jwt = require('express-jwt');
var blacklist = require('express-jwt-blacklist');

// ruleid: rules_lgpl_javascript_jwt_rule-jwt-not-revoked
app.get('/ok-protected', jwt({ secret: process.env.SECRET }), function (req, res) {
    if (!req.user.admin) return res.sendStatus(401);
    res.sendStatus(200);
});

let configSecret = config.get('secret')
const opts = Object.assign({ issuer: 'http://issuer' }, { secret: configSecret })
// ruleid: rules_lgpl_javascript_jwt_rule-jwt-not-revoked
app.get('/ok-protected', jwt(opts), function (req, res) {
    if (!req.user.admin) return res.sendStatus(401);
    res.sendStatus(200);
});