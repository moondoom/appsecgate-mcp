// License: GNU Lesser General Public License v3.0
// source (original): https://github.com/ajinabraham/njsscan/blob/master/tests/assets/node_source/true_positives/semantic_grep/xss/xss_templates.js
// hash: e7a0a61
const Sqrl = require('squirrelly')

module.exports = function (app) {
    // Sqrl.autoEscaping is only availble in squirrelly 7.*.*('XSS Attack')</script>
    app.get("/xss/squirrelly/1", async (req, res) => {
        var myTemplate = "Alert shown using req.query.message {{message}}</p>"
        // ruleid: rules_lgpl_javascript_xss_rule-squirrelly-autoescape
        Sqrl.autoEscaping(false)
        res.send(Sqrl.Render(myTemplate, {message: req.query.message})) 
    });

    app.get("/xss/squirrelly/safe/1", async (req, res) => {
        var myTemplate = "<p>My Message is: {{message}}</p>"
        // ok: rules_lgpl_javascript_xss_rule-squirrelly-autoescape
        Sqrl.autoEscaping(true)
        res.send(Sqrl.Render(myTemplate, {message: req.query.message})) 
    });

    app.get("/xss/squirrelly/safe/2", async (req, res) => {
        var myTemplate = "<p>My Message is: {{message}}</p>"
        // ok: rules_lgpl_javascript_xss_rule-squirrelly-autoescape
        res.send(Sqrl.Render(myTemplate, {message: req.query.message})) 
    });
};


import express from "express";
import Sqrl from 'squirrelly';

const router = express.Router();

router.route("/1").get((req, res) => {
    var myTemplate = "Alert shown using req.query.message {{message}}</p>"
    // ruleid: rules_lgpl_javascript_xss_rule-squirrelly-autoescape
    Sqrl.autoEscaping(false)
    res.send(Sqrl.Render(myTemplate, {message: req.query.message})) 
})

router.route("/safe/1").get((req, res) => {
    var myTemplate = "<p>My Message is: {{message}}</p>"
    // ok: rules_lgpl_javascript_xss_rule-squirrelly-autoescape
    Sqrl.autoEscaping(true)
    res.send(Sqrl.Render(myTemplate, {message: req.query.message})) 
})

router.route("/safe/2").get((req, res) => {
    var myTemplate = "<p>My Message is: {{message}}</p>"
    // ok: rules_lgpl_javascript_xss_rule-squirrelly-autoescape
    res.send(Sqrl.Render(myTemplate, {message: req.query.message})) 
})

export default router;
