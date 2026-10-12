// License: GNU Lesser General Public License v3.0
// source (original): https://github.com/ajinabraham/njsscan/blob/master/tests/assets/node_source/true_positives/semantic_grep/xss/xss_templates.js
// hash: e7a0a61
const hbl = require("handlebars");

module.exports = function (app) {
  // http://localhost:3000/xss/handlebars/safe-string/1?message=%3Cscript%3Ealert(%27xss%27)%3C/script%3E
  app.get("/xss/handlebars/safe-string/1", async (req, res) => {
    // ruleid: rules_lgpl_javascript_xss_rule-handlebars-safestring
    var returnObj = new hbl.SafeString("<h1>Handlebars safe string</h1>" +  req.query.message)
    res.send(returnObj.string)
  });

  // http://localhost:3000/xss/handlebars/safe-string/safe/1?message=%3Cscript%3Ealert(%27xss%27)%3C/script%3E
  app.get("/xss/handlebars/safe-string/safe/1", async (req, res) => {
    // ok: rules_lgpl_javascript_xss_rule-handlebars-safestring
    var returnObj = new hbl.SafeString("<h1>Handlebars safe string</h1>" + hbl.escapeExpression(req.query.message))
    res.send(returnObj.string)
  });

  // http://localhost:3000/xss/handlebars/safe-string/safe/2?message=%3Cscript%3Ealert(%27xss%27)%3C/script%3E
  app.get("/xss/handlebars/safe-string/safe/2", async (req, res) => {
    var msg = hbl.escapeExpression(req.query.message);
    // ok: rules_lgpl_javascript_xss_rule-handlebars-safestring
    var returnObj = new hbl.SafeString("<h1>Handlebars safe string</h1>" + msg)
    res.send(returnObj.string)
  });

  // http://localhost:3000/xss/handlebars/safe-string/safe/3
  app.get("/xss/handlebars/safe-string/safe/3", async (req, res) => {
    // ok: rules_lgpl_javascript_xss_rule-handlebars-safestring
    var returnObj = new hbl.SafeString("<h1>Handlebars safe string</h1>")
    res.send(returnObj.string)
  });
};

import Handlebars from "handlebars";
import express from "express";

const router = express.Router();

router.route("/1").get(async (req, res) => {
    // ruleid: rules_lgpl_javascript_xss_rule-handlebars-safestring
    var returnObj = new Handlebars.SafeString("<h1>Handlebars safe string</h1>" +  req.query.message)
    res.send(returnObj.string)
});

// http://localhost:3000/xss/handlebars/safe-string/safe/1?message=<script>alert('xss')</script>
router.route("/safe/1").get(async (req, res) => {
  // ok: rules_lgpl_javascript_xss_rule-handlebars-safestring
  var returnObj = new Handlebars.SafeString("<h1>Handlebars safe string</h1>" +  Handlebars.escapeExpression(req.query.message))
  res.send(returnObj.string)
});

// http://localhost:3000/xss/handlebars/safe-string/safe/2
router.route("/safe/2").get(async (req, res) => {
  const msg = "msg"
  // ok: rules_lgpl_javascript_xss_rule-handlebars-safestring
  var returnObj = new Handlebars.SafeString("<h1>Handlebars safe string</h1>" +  msg)
  res.send(returnObj.string)
});

export default router;