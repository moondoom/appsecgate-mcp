// License: GNU Lesser General Public License v3.0
// source (original): https://github.com/ajinabraham/njsscan/blob/master/tests/assets/node_source/true_positives/semantic_grep/xss/xss_templates.js
// hash: e7a0a61
var Handlebars = require('handlebars');

module.exports = function (app) {

  // http://localhost:3000/xss/handlebars/noescape/1?message=<script>alert('XSS')</script>
  app.get("/xss/handlebars/noescape/1", async (req, res) => { 
    var template = "This is {{target}}";
    // ruleid: rules_lgpl_javascript_xss_rule-handlebars-noescape
    var out = Handlebars.compile(template, {noEscape: true})({target: req.query.message});
    res.send(out);
  });

   // http://localhost:3000/xss/handlebars/noescape/2?message=<script>alert('XSS')</script>
   app.get("/xss/handlebars/noescape/2", async (req, res) => { 
    var template = "This is {{target}}";
    // ruleid: rules_lgpl_javascript_xss_rule-handlebars-noescape
    var outFn = Handlebars.compile(template, {noEscape: true});
    var out = outFn({target: req.query.message});
    res.send(out);
  });

  // http://localhost:3000/xss/handlebars/noescape/safe/1?message=<script>alert('XSS')</script>
  app.get("/xss/handlebars/noescape/safe/1", async (req, res) => { 
    var template = "This is {{target}}";
    // ok: rules_lgpl_javascript_xss_rule-handlebars-noescape
    var out = Handlebars.compile(template)({target: req.query.message});
    res.send(out);
  });

  // http://localhost:3000/xss/handlebars/noescape/safe/2?message=<script>alert('sd')</script>
  app.get("/xss/handlebars/noescape/safe/2", async (req, res) => {
    var template = "This is {{target}}";
    // ok: rules_lgpl_javascript_xss_rule-handlebars-noescape
    var out = Handlebars.compile(template, {noEscape: false})({target: req.query.message});
    res.send(out);
  }); 

   // http://localhost:3000/xss/handlebars/noescape/safe/3?message=<script>alert('sd')</script>
   app.get("/xss/handlebars/noescape/safe/3", async (req, res) => {
    var template = "This is {{target}}";
    // ok: rules_lgpl_javascript_xss_rule-handlebars-noescape
    var out = Handlebars.compile(template, {noEscape: true})({target: "target"});
    res.send(out);
  });
}

import express from "express";
import HandleBars from "handlebars";

const router = express.Router();

// http://localhost:3000/xss/handlebars/noescape/1?message=<script>alert('XSS')</script>
router.route("/1").get(async (req, res) => {
    var template = "This is {{target}}";
    // ruleid: rules_lgpl_javascript_xss_rule-handlebars-noescape
    var out = HandleBars.compile(template, { noEscape: true })({ target: req.query.message });
    res.send(out);
});

// http://localhost:3000/xss/handlebars/noescape/1?message=<script>alert('XSS')</script>
router.route("/2").get(async (req, res) => {
    var template = "This is {{target}}";
    // ruleid: rules_lgpl_javascript_xss_rule-handlebars-noescape
    var outFn = HandleBars.compile(template, { noEscape: true });
    var out = outFn({ target: req.query.message })
    res.send(out);
});

// http://localhost:3000/xss/handlebars/noescape/3?message=<script>alert('XSS')</script>
router.route("/3").get(async (req, res) => {
    var template = "This is {{target}}";
    var trueVar = true;
    // ruleid: rules_lgpl_javascript_xss_rule-handlebars-noescape
    var outFn = HandleBars.compile(template, { noEscape: trueVar });
    var out = outFn({ target: req.query.message })
    res.send(out);
});

// http://localhost:3000/xss/handlebars/noescape/safe/1?message=<script>alert('XSS')</script>
router.route("/safe/1").get(async (req, res) => {
    var template = "This is {{target}}";
    // ok: rules_lgpl_javascript_xss_rule-handlebars-noescape
    var out = HandleBars.compile(template)({ target: req.query.message });
    res.send(out);
});

// http://localhost:3000/xss/handlebars/noescape/safe/2?message=<script>alert('sd')</script>
router.route("/safe/2").get(async (req, res) => {
    var template = "This is {{target}}";
    // ok: rules_lgpl_javascript_xss_rule-handlebars-noescape
    var out = HandleBars.compile(template, { noEscape: false })({ target: req.query.message });
    res.send(out);
});

// http://localhost:3000/xss/handlebars/noescape/safe/3?message=<script>alert('sd')</script>
router.route("/safe/3").get(async (req, res) => {
    var template = "This is {{target}}";
    var target = "target";
    // ok: rules_lgpl_javascript_xss_rule-handlebars-noescape
    var out = HandleBars.compile(template, { noEscape: false })({ target: target });
    res.send(out);
});

// http://localhost:3000/xss/handlebars/noescape/safe/4?message=<script>alert('sd')</script>
router.route("/safe/4").get(async (req, res) => {
    var template = "This is {{target}}";
    var falseVar = false
    // ok: rules_lgpl_javascript_xss_rule-handlebars-noescape
    var out = HandleBars.compile(template, { noEscape: falseVar })({ target: req.query.message });
    res.send(out);
});

// http://localhost:3000/xss/handlebars/noescape/safe/5?message=<script>alert('sd')</script>
router.route("/safe/5").get(async (req, res) => {
    var template = "This is {{target}}";
    var falseVar = false
    // ok: rules_lgpl_javascript_xss_rule-handlebars-noescape
    var out = HandleBars.compile(template, { noEscape: true })({ target: "target" });
    res.send(out);
});

export default router