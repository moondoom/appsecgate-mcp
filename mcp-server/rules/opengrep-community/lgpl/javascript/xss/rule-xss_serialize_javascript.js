// License: GNU Lesser General Public License v3.0
// source (original): https://github.com/ajinabraham/njsscan/blob/master/tests/assets/node_source/true_positives/semantic_grep/xss/xss_serialize_js.js
// hash: e7a0a61
var serialize = require('serialize-javascript');

module.exports = function (app) {
  //http://localhost:3000/xss/serialize/1?message=<script>alert('sd')</script>
  app.get("/xss/serialize/1", async (req, res) => {
    const htmlResponse = req.query.message + "The alert was shown from the query param";
    // ruleid: rules_lgpl_javascript_xss_rule-xss-serialize-javascript
    const jsObj = serialize({
      foo: htmlResponse
    }, { unsafe: true });
    res.send(jsObj);
  });

  //http://localhost:3000/xss/serialize/2?message=<script>alert('sd')</script>
  app.get("/xss/serialize/2", async (req, res) => {
    const htmlResponse = req.query.message + "The alert was shown from the query param";
    // ruleid: rules_lgpl_javascript_xss_rule-xss-serialize-javascript
    const jsObj = serialize({
      foo: htmlResponse
    }, { space: 1, unsafe: true, isJSON: false });
    res.send(jsObj);
  });

  //http://localhost:3000/xss/serialize/safe/1?message=<script>alert('sd')</script>
  app.get("/xss/serialize/safe/1", async (req, res) => {
    const htmlResponse = req.query.message + "The alert was shown from the query param";
    // ok: rules_lgpl_javascript_xss_rule-xss-serialize-javascript
    const jsObj = serialize({
      foo: htmlResponse
    });
    res.send(jsObj);
  });

  //http://localhost:3000/xss/serialize/safe/2?message=<script>alert('sd')</script>
  app.get("/xss/serialize/safe/2", async (req, res) => {
    const htmlResponse = req.query.message + "The alert was shown from the query param";
    // ok: rules_lgpl_javascript_xss_rule-xss-serialize-javascript
    const jsObj = serialize({
      foo: htmlResponse
    }, { unsafe: false });
    res.send(jsObj);
  });

  //http://localhost:3000/xss/serialize/safe/3?message=<script>alert('sd')</script>
  app.get("/xss/serialize/safe/3", async (req, res) => {
    const htmlResponse = req.query.message + "The alert was shown from the query param";
    // ok: rules_lgpl_javascript_xss_rule-xss-serialize-javascript
    const jsObj = serialize({
      foo: htmlResponse
    }, { space: 1, unsafe: false, isJSON: false });
    res.send(jsObj);
  });
}

import serialize from "serialize-javascript";
import express from "express";

const router = express.Router();

//http://localhost:3000/xss/serialize/1?message=<script>alert('sd')</script>
router.route("/1").get(async (req, res) => {
    const htmlResponse = req.query.message + "The alert was shown from the query param";
    // ruleid: rules_lgpl_javascript_xss_rule-xss-serialize-javascript
    const jsObj = serialize({
        foo: htmlResponse
    }, { unsafe: true });
    res.send(jsObj);
});

//http://localhost:3000/xss/serialize/2?message=<script>alert('sd')</script>
router.route("/2").get(async (req, res) => {
  const htmlResponse = req.query.message + "The alert was shown from the query param";
  // ruleid: rules_lgpl_javascript_xss_rule-xss-serialize-javascript
  const jsObj = serialize({
      foo: htmlResponse
  }, { pace: 1, unsafe: true, isJSON: false });
  res.send(jsObj);
});

//http://localhost:3000/xss/serialize/safe/1?message=<script>alert('sd')</script>
router.route("/safe/1").get(async (req, res) => {
    const htmlResponse = req.query.message + "The alert was shown from the query param";
    // ok: rules_lgpl_javascript_xss_rule-xss-serialize-javascript
    const jsObj = serialize({
        foo: htmlResponse
    });
    res.send(jsObj);
});

//http://localhost:3000/xss/serialize/safe/2?message=<script>alert('sd')</script>
router.route("/safe/2").get(async (req, res) => {
    const htmlResponse = req.query.message + "The alert was shown from the query param";
    // ok: rules_lgpl_javascript_xss_rule-xss-serialize-javascript
    const jsObj = serialize({
        foo: htmlResponse
    }, { unsafe: false });
    res.send(jsObj);
});

//http://localhost:3000/xss/serialize/safe/3?message=<script>alert('sd')</script>
router.route("/safe/3").get(async (req, res) => {
  const htmlResponse = req.query.message + "The alert was shown from the query param";
  // ok: rules_lgpl_javascript_xss_rule-xss-serialize-javascript
  const jsObj = serialize({
      foo: htmlResponse
  }, { pace: 1, unsafe: false, isJSON: false});
  res.send(jsObj);
});

export default router;