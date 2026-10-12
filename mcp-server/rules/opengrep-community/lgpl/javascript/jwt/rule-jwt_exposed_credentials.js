// License: GNU Lesser General Public License v3.0
// source (original): https://github.com/ajinabraham/njsscan/blob/master/tests/assets/node_source/true_positives/semantic_grep/jwt/jwt_exposed_credentials.js
// hash: e7a0a61
const jwt = require("jsonwebtoken");
const jose = require("jose")

const secretKey = "this is the secret key"

module.exports = function (app) {
    // http://localhost:3000/jwt/jwt_exposed_credentials/jsonwebtoken/1
    app.get('/jwt/jwt_exposed_credentials/jsonwebtoken/1', (req, res) => {
        const payload = { user_id: 123, password: 'john_doe' };
        // ruleid: rules_lgpl_javascript_jwt_rule-jwt-exposed-credentials
        const token = jwt.sign(payload, secretKey, { algorithm: 'HS256' });
        console.log('Generated Token:', token);
        res.send({ token })
    })

    // http://localhost:3000/jwt/jwt_exposed_credentials/jsonwebtoken/2
    app.get('/jwt/jwt_exposed_credentials/jsonwebtoken/2', (req, res) => {
        // ruleid: rules_lgpl_javascript_jwt_rule-jwt-exposed-credentials
        const token = jwt.sign({ user_id: 123, password: 'john_doe' }, secretKey, { algorithm: 'HS256' });
        console.log('Generated Token:', token);
        res.send({ token })
    })

    // http://localhost:3000/jwt/jwt_exposed_credentials/jsonwebtoken/3
    app.get('/jwt/jwt_exposed_credentials/jsonwebtoken/3', (req, res) => {
        const payload = { user_id: 123, username: 'john_doe' };
        // ruleid: rules_lgpl_javascript_jwt_rule-jwt-exposed-credentials
        const token = jwt.sign(Object.assign(payload, { password: "password" }), secretKey, { algorithm: 'HS256' });
        console.log('Generated Token:', token);
        res.send({ token })
    })

    // http://localhost:3000/jwt/jwt_exposed_credentials/jsonwebtoken/4
    app.get('/jwt/jwt_exposed_credentials/jsonwebtoken/4', (req, res) => {
        const payload = { user_id: 123, username: 'john_doe' };
        const passwordObj = { password: "password" }
        // ruleid: rules_lgpl_javascript_jwt_rule-jwt-exposed-credentials
        const token = jwt.sign(Object.assign(payload, passwordObj), secretKey, { algorithm: 'HS256' });
        console.log('Generated Token:', token);
        res.send({ token })
    })

    // http://localhost:3000/jwt/jwt_exposed_credentials/jsonwebtoken/5
    app.get('/jwt/jwt_exposed_credentials/jsonwebtoken/5', (req, res) => {
        const payload = { user_id: 123, username: 'john_doe' };
        payload.password = "password"
        // ruleid: rules_lgpl_javascript_jwt_rule-jwt-exposed-credentials
        const token = jwt.sign(payload, secretKey, { algorithm: 'HS256' });
        console.log('Generated Token:', token);
        res.send({ token })
    })

    // http://localhost:3000/jwt/jwt_exposed_credentials/jsonwebtoken/safe/1
    app.get('/jwt/jwt_exposed_credentials/jsonwebtoken/safe/1', (req, res) => {
        const payload = { user_id: 123, username: 'john_doe' };
        // ok: rules_lgpl_javascript_jwt_rule-jwt-exposed-credentials
        const token = jwt.sign(payload, secretKey, { algorithm: 'HS256' });
        console.log('Generated Token:', token);
        res.send({ token })
    })

    // http://localhost:3000/jwt/jwt_exposed_credentials/jsonwebtoken//safe/2
    app.get('/jwt/jwt_exposed_credentials/jsonwebtoken/safe/2', (req, res) => {
        const payload = { user_id: 123, username: 'john_doe' };
        payload.userEmail = "user@Example.com"
        // ok: rules_lgpl_javascript_jwt_rule-jwt-exposed-credentials
        const token = jwt.sign(payload, secretKey, { algorithm: 'HS256' });
        console.log('Generated Token:', token);
        res.send({ token })
    })

    // http://localhost:3000/jwt/jwt_exposed_credentials/jose/1
    app.get('/jwt/jwt_exposed_credentials/jose/1', async (req, res) => {
        const payload = { user_id: 123, stepOne: { stepTwo: { user_id: 123, password: 'john_doe' } } };
        const key = new TextEncoder().encode(
            'cc7e0d44fd473002f1c42167459001140ec6389b7353f8088f4d9a95f2f596f2'
        )
        // ruleid: rules_lgpl_javascript_jwt_rule-jwt-exposed-credentials
        let token = await new jose.SignJWT(payload)
            .setProtectedHeader({ alg: 'HS256' })
            .setIssuedAt()
            .setIssuer('urn:example:issuer')
            .setAudience('urn:example:audience')
            .setExpirationTime('2h')
            .sign(key)
        res.send({ token })
    })

    // http://localhost:3000/jwt/jwt_exposed_credentials/jose/2
    app.get('/jwt/jwt_exposed_credentials/jose/2', async (req, res) => {
        const key = Uint8Array.from(
            'cc7e0d44fd473002f1c42167459001140ec6389b7353f8088f4d9a95f2f596f2',
        )
        // ruleid: rules_lgpl_javascript_jwt_rule-jwt-exposed-credentials
        let jwt = new jose.SignJWT({ user_id: 123, stepOne: { stepTwo: { user_id: 123, password: 'john_doe' } } }).setProtectedHeader({ alg: 'HS256', sign_type: 'SIGN' });
        let token = await jwt.sign(key);
        console.log({ token })
        res.send({ token })
    })

    // http://localhost:3000/jwt/jwt_exposed_credentials/jose/3
    app.get('/jwt/jwt_exposed_credentials/jose/3', async (req, res) => {
        const key = Uint8Array.from(
            'cc7e0d44fd473002f1c42167459001140ec6389b7353f8088f4d9a95f2f596f2',
        )

        var payload = { user_id: 123, stepOne: { stepTwo: { user_id: 123 } } }
        payload.password = "password"

        // ruleid: rules_lgpl_javascript_jwt_rule-jwt-exposed-credentials
        let jwt = new jose.SignJWT(payload).setProtectedHeader({ alg: 'HS256', sign_type: 'SIGN' });
        let token = await jwt.sign(key);
        console.log({ token })
        res.send({ token })
    })

    // http://localhost:3000/jwt/jwt_exposed_credentials/jose/safe/1
    app.get('/jwt/jwt_exposed_credentials/jose/safe/1', async (req, res) => {
        const key = Uint8Array.from(
            'cc7e0d44fd473002f1c42167459001140ec6389b7353f8088f4d9a95f2f596f2',
        )

        var payload = { user_id: 123, stepOne: { stepTwo: { user_id: 123 } } }
        payload.email = "user@example.com"

        // ok: rules_lgpl_javascript_jwt_rule-jwt-exposed-credentials
        let jwt = new jose.SignJWT(payload).setProtectedHeader({ alg: 'HS256', sign_type: 'SIGN' });
        let token = await jwt.sign(key);
        console.log({ token })
        res.send({ token })
    })
}

import express from "express";
import jwt from "jsonwebtoken"
import * as jose from 'jose'

const router = express.Router();

// http://localhost:3000/jwt/jwt_exposed_credentials/jsonwebtoken/1
router.route("/jsonwebtoken/1").get((req, res) => {
    const payload = { user_id: 123, password: 'john_doe' };
    // ruleid: rules_lgpl_javascript_jwt_rule-jwt-exposed-credentials
    const token = jwt.sign(payload, secretKey, { algorithm: 'HS256' });
    console.log('Generated Token:', token);
    res.send({ token })
})

// http://localhost:3000/jwt/jwt_exposed_credentials/jsonwebtoken/2
router.route("/jsonwebtoken/2").get((req, res) => {
    // ruleid: rules_lgpl_javascript_jwt_rule-jwt-exposed-credentials
    const token = jwt.sign({ user_id: 123, password: 'john_doe' }, secretKey, { algorithm: 'HS256' });
    console.log('Generated Token:', token);
    res.send({ token })
})

// http://localhost:3000/jwt/jwt_exposed_credentials/jsonwebtoken/3
router.route("/jsonwebtoken/3").get((req, res) => {
    const payload = { user_id: 123, username: 'john_doe' };
    // ruleid: rules_lgpl_javascript_jwt_rule-jwt-exposed-credentials
    const token = jwt.sign(Object.assign(payload, { password: "password" }), secretKey, { algorithm: 'HS256' });
    console.log('Generated Token:', token);
    res.send({ token })
})

// http://localhost:3000/jwt/jwt_exposed_credentials/jsonwebtoken/safe/1
router.route("/jsonwebtoken/safe/1").get((req, res) => {
    const payload = { user_id: 123, username: 'john_doe' };
    // ok: rules_lgpl_javascript_jwt_rule-jwt-exposed-credentials
    const token = jwt.sign(Object.assign(payload, { email: "use@email.com" }), secretKey, { algorithm: 'HS256' });
    console.log('Generated Token:', token);
    res.send({ token })
})

// http://localhost:3000/jwt/jwt_exposed_credentials/jose/1
router.route("/jose/1").get(async (req, res) => {
    const payload = { user_id: 123, stepOne: { stepTwo: { user_id: 123, password: 'john_doe' } } };
        const key = new TextEncoder().encode(
            'cc7e0d44fd473002f1c42167459001140ec6389b7353f8088f4d9a95f2f596f2'
        )
        // ruleid: rules_lgpl_javascript_jwt_rule-jwt-exposed-credentials
        let token = await new jose.SignJWT(payload)
            .setProtectedHeader({ alg: 'HS256' })
            .setIssuedAt()
            .setIssuer('urn:example:issuer')
            .setAudience('urn:example:audience')
            .setExpirationTime('2h')
            .sign(key)
        res.send({ token })
})

// http://localhost:3000/jwt/jwt_exposed_credentials/jose/2
router.route("/jose/2").get(async (req, res) => {
    const key = Uint8Array.from(
        'cc7e0d44fd473002f1c42167459001140ec6389b7353f8088f4d9a95f2f596f2',
    )
    // ruleid: rules_lgpl_javascript_jwt_rule-jwt-exposed-credentials
    let jwt = new jose.SignJWT({ user_id: 123, stepOne: { stepTwo: { user_id: 123, password: 'john_doe' } } }).setProtectedHeader({ alg: 'HS256', sign_type: 'SIGN' });
    let token = await jwt.sign(key);
    console.log({ token })
    res.send({ token })
})

// http://localhost:3000/jwt/jwt_exposed_credentials/jose/3
router.route("/jose/3").get(async (req, res) => {
    const key = Uint8Array.from(
        'cc7e0d44fd473002f1c42167459001140ec6389b7353f8088f4d9a95f2f596f2',
    )
    var payload = { user_id: 123, stepOne: { stepTwo: { user_id: 123 } } }
    payload.userPassword = "QAswdef23!@" 
    // ruleid: rules_lgpl_javascript_jwt_rule-jwt-exposed-credentials
    let jwt = new jose.SignJWT(payload).setProtectedHeader({ alg: 'HS256', sign_type: 'SIGN' });
    let token = await jwt.sign(key);
    console.log({ token })
    res.send({ token })
})

// http://localhost:3000/jwt/jwt_exposed_credentials/jose/safe/1
router.route("/jose/safe/1").get(async (req, res) => {
    const payload = { user_id: 123, stepOne: { stepTwo: { user_id: 123, email: 'john_doe' } } };
        const key = new TextEncoder().encode(
            'cc7e0d44fd473002f1c42167459001140ec6389b7353f8088f4d9a95f2f596f2'
        )
        // ok: rules_lgpl_javascript_jwt_rule-jwt-exposed-credentials
        let token = await new jose.SignJWT(payload)
            .setProtectedHeader({ alg: 'HS256' })
            .setIssuedAt()
            .setIssuer('urn:example:issuer')
            .setAudience('urn:example:audience')
            .setExpirationTime('2h')
            .sign(key)
        res.send({ token })
})

// http://localhost:3000/jwt/jwt_exposed_credentials/jose/safe/2
router.route("/jose/safe/2").get(async (req, res) => {
    const key = Uint8Array.from(
        'cc7e0d44fd473002f1c42167459001140ec6389b7353f8088f4d9a95f2f596f2',
    )
    // ok: rules_lgpl_javascript_jwt_rule-jwt-exposed-credentials
    let jwt = new jose.SignJWT({ user_id: 123, stepOne: { stepTwo: { user_id: 123, email: 'john_doe'  } } }).setProtectedHeader({ alg: 'HS256', sign_type: 'SIGN' });
    let token = await jwt.sign(key);
    console.log({ token })
    res.send({ token })
})

export default router;