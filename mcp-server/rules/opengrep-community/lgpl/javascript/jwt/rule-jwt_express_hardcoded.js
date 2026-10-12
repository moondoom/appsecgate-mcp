// License: GNU Lesser General Public License v3.0
// source (original): https://github.com/ajinabraham/njsscan/blob/master/tests/assets/node_source/true_positives/semantic_grep/jwt/jwt_express_hardcoded.js
// hash: e7a0a61
var { expressjwt } = require('express-jwt');
var { expressjwt: jwt } = require('express-jwt');

module.exports = function (app) {
    // http://localhost:3000/jwt/express-hardcoded/auth-route-1
    app.get("/jwt/express-hardcoded/auth-route-1",
        // ruleid: rules_lgpl_javascript_jwt_rule-jwt-express-hardcoded
        expressjwt({ secret: "secretKey", algorithms: ['HS256'] }),
        async (req, res) => {
            res.send("auth route");
        });

    // http://localhost:3000/jwt/express-hardcoded/auth-route-2
    const options = { secret: "secretKey", algorithms: ['HS256'] }
    app.get("/jwt/express-hardcoded/auth-route-2",
        // ruleid: rules_lgpl_javascript_jwt_rule-jwt-express-hardcoded
        expressjwt(options),
        async (req, res) => {
            res.send("auth route");
        });

    // http://localhost:3000/jwt/express-hardcoded/free-route-1
    app.get("/jwt/express-hardcoded/free-route-1",
        async (req, res) => {
            res.send("free route");
        });

    // http://localhost:3000/jwt/express-hardcoded/auth-route-3    
    app.get('/jwt/express-hardcoded/auth-route-3',
        // ruleid:rules_lgpl_javascript_jwt_rule-jwt-express-hardcoded
        jwt({ secret: 'shhhhhhared-secret', algorithms: ['HS256'] }), function (req, res) {
            if (!req.user.admin) return res.sendStatus(401);
            res.sendStatus(200);
        });

    let hardcodedSecret = 'shhhhhhared-secret'

    // http://localhost:3000/jwt/express-hardcoded/auth-route-4
    // ruleid:rules_lgpl_javascript_jwt_rule-jwt-express-hardcoded
    app.get('/jwt/express-hardcoded/auth-route-4', jwt({ secret: hardcodedSecret, algorithms: ['HS256'] }), function (req, res) {
        if (!req.user.admin) return res.sendStatus(401);
        res.sendStatus(200);
    });

    let secret = "hardcode"
    const opts = Object.assign({ issuer: 'http://issuer' }, { secret, algorithms: ['HS256'] })

    // http://localhost:3000/jwt/express-hardcoded/auth-route-5
    // ruleid:rules_lgpl_javascript_jwt_rule-jwt-express-hardcoded
    app.get('/jwt/express-hardcoded/auth-route-5', jwt(opts), function (req, res) {
        if (!req.user.admin) return res.sendStatus(401);
        res.sendStatus(200);
    });

    let secret2 = { secret: "hardcode" }
    const opts2 = Object.assign({ issuer: 'http://issuer' }, secret2, {  algorithms: ['HS256'] })
    // http://localhost:3000/jwt/express-hardcoded/auth-route-6
    // ruleid:rules_lgpl_javascript_jwt_rule-jwt-express-hardcoded
    app.get('/jwt/express-hardcoded/auth-route-6', jwt(opts2), function (req, res) {
        if (!req.user.admin) return res.sendStatus(401);
        res.sendStatus(200);
    });
}

import express from "express";
import { expressjwt } from 'express-jwt';

const router = express.Router();

const secretKey = 'yourSecretKey';

// http://localhost:3000/jwt/express-hardcoded/auth-route-1
router.route("/auth-route-1").get(
    // ruleid: rules_lgpl_javascript_jwt_rule-jwt-express-hardcoded
    expressjwt({ secret: "secretKey", algorithms: ['HS256'] }),
    (req, res) => {
        res.send('Token is valid');
    }
);

// http://localhost:3000/jwt/express-hardcoded/auth-route-2
router.route("/auth-route-2").get(
    // ruleid: rules_lgpl_javascript_jwt_rule-jwt-express-hardcoded
    expressjwt({ secret: secretKey, algorithms: ['HS256'] }),
    (req, res) => {
        res.send('Token is valid');
    }
);

const options = { secret: secretKey, algorithms: ['HS256'] }
// http://localhost:3000/jwt/express-hardcoded/auth-route-3
router.route("/auth-route-2").get(
    // ruleid: rules_lgpl_javascript_jwt_rule-jwt-express-hardcoded
    expressjwt(options),
    (req, res) => {
        res.send('Token is valid');
    }
);

let secret2 = { secret: "hardcode" }
const opts2 = Object.assign({ issuer: 'http://issuer' }, secret2, { algorithms: ['HS256'] })
// http://localhost:3000/jwt/express-hardcoded/auth-route-3
router.route("/auth-route-3").get(
    // ruleid: rules_lgpl_javascript_jwt_rule-jwt-express-hardcoded
    expressjwt(opts2),
    (req, res) => {
        res.send('Token is valid');
    }
);

// http://localhost:3000/jwt/express-hardcoded/safe-route
router.route("/safe-route").get(
    // ok: rules_lgpl_javascript_jwt_rule-jwt-express-hardcoded
    expressjwt({ secret: process.env.SECRET, algorithms: ['HS256'] }),
    (req, res) => {
        res.send('Token is valid');
    }
);

export default router;