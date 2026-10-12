// License: GNU Lesser General Public License v3.0
// source (original): https://github.com/ajinabraham/njsscan/blob/master/tests/assets/node_source/true_positives/semantic_grep/xml/xpathi_node.js
// hash: e7a0a61
var xpath = require('xpath');
var dom = require('@xmldom/xmldom').DOMParser;
var fs = require('fs');

let getXMLFile = function (callback) {
  let xml_string = fs.readFileSync("books.xml", "utf8");
  var doc = new dom().parseFromString(xml_string, 'text/xml');
  callback(doc);
}

module.exports = function (app) {

  // Vulnerable poc : http://localhost:3000/xml/xpath/1a?name=//book[price%3e30]/price
  // http://localhost:3000/xml/xpath/1a?name=//title
  app.get('/xml/xpath/1a', async (req, res) => {
    var nodes
    getXMLFile(function (doc) {
      // ruleid:rules_lgpl_javascript_xml_rule-node-xpath-injection
      var evaluator = xpath.parse(req.param('name'))
      nodes = evaluator.select({ node: doc })
      console.log("using req.param('name') - ", nodes[0].firstChild.data)
    })
    res.send(nodes[0].firstChild.data)
  }) 

  // Vulnerable poc : http://localhost:3000/xml/xpath/1?name=book[price%3e30]/price  
  // http://localhost:3000/xml/xpath/1?name=title
  app.get("/xml/xpath/1", async (req, res) => {
    var nodes;    
    getXMLFile(function (doc) {
      // ruleid:rules_lgpl_javascript_xml_rule-node-xpath-injection
      var evaluator = xpath.parse("//"+req.param("name"));
      nodes = evaluator.select({ node: doc });
      console.log("using req.param('name') - ", nodes[0].firstChild.data);
    });
    res.send(nodes[0].firstChild.data);
  });

  // Vulnerable poc : http://localhost:3000/xml/xpath/2/book[title=%22Learning%20XML%22]%2Fprice  
  // http://localhost:3000/xml/xpath/2/title
  app.get("/xml/xpath/2/:name", async (req, res) => {
    var nodes;    
    getXMLFile(function (doc) {
      // ruleid:rules_lgpl_javascript_xml_rule-node-xpath-injection
      var evaluator = xpath.parse("//"+req.params.name);
      nodes = evaluator.select({ node: doc });
      console.log("using req.params.name - ", nodes[0].firstChild.data);
    });
    res.send(nodes[0].firstChild.data);
  });

  // Vulnerable poc : http://localhost:3000/xml/xpath/3/book[price%3E30]%2Ftitle
  // http://localhost:3000/xml/xpath/3/title
  app.get("/xml/xpath/3/:name", async (req, res) => {
    var nodes;    
    getXMLFile(function (doc) {
      // ruleid:rules_lgpl_javascript_xml_rule-node-xpath-injection
      var evaluator = xpath.parse("//"+req.params["name"]);
      nodes = evaluator.select({ node: doc });
      console.log("using req.params['name'] - ", nodes[0].firstChild.data);
    });
    res.send(nodes[0].firstChild.data);
  });

  // Vulnerable poc : http://localhost:3000/xml/xpath/4?name=book[price%3e30]/title
  // http://localhost:3000/xml/xpath/4?name=title
  app.get("/xml/xpath/4", async (req, res) => {
    var nodes;    
    getXMLFile(function (doc) {
      // ruleid:rules_lgpl_javascript_xml_rule-node-xpath-injection
      var evaluator = xpath.parse("//"+req.query.name);
      nodes = evaluator.select({ node: doc });
      console.log("using req.query.name - ", nodes[0].firstChild.data);
    });
    res.send(nodes[0].firstChild.data);
  });

  // Exploit poc : http://localhost:3000/xml/xpath/4?name=book[title=%22Learning%20XML%22]/price
  // Safe - will not be exploited.
  // http://localhost:3000/xml/xpath/5?name=title
  app.get("/xml/xpath/5", async (req, res) => {    
    var nodes;    
    getXMLFile(function (doc) {
      // ok:rules_lgpl_javascript_xml_rule-node-xpath-injection
      var evaluator = xpath.parse("//title");
      nodes = evaluator.select({ node: doc });
      console.log("using const string - ", nodes[0].firstChild.data);
    });
    res.send(nodes[0].firstChild.data);
  });

  // Safe - will not be exploited.
  const allowedExpr = [ 'title' ];

  // http://localhost:3000/xml/xpath/6?name=title
  app.get("/xml/xpath/6", async (req, res) => {    
    var nodes;
    var isAllowed = allowedExpr.includes(req.query.name);    
    getXMLFile(function (doc) {
      if (isAllowed) {
        // ok:rules_lgpl_javascript_xml_rule-node-xpath-injection
        var evaluator = xpath.parse(req.query.name);
        nodes = evaluator.select({ node: doc });
        console.log("using const string - ", nodes[0].firstChild.data);
      }
    });
    res.send(nodes[0].firstChild.data);
    myFunction1(req, res);
    myFunction2(req, res);
  });
}

export const Blah = (one, two) => {
  let heyyy;
  if (one['hi']) {
    // ok:rules_lgpl_javascript_xml_rule-node-xpath-injection
    heyyy = JSON.parse(one['hi']);
  }
}

import { parse as x } from 'xpath';
function myFunction1 (req, res) {
  var xpath2;
  var nodes;
  // ruleid:rules_lgpl_javascript_xml_rule-node-xpath-injection
  var evaluator = x(req.query.name);
  // ok :rules_lgpl_javascript_xml_rule-node-xpath-injection
  var evaluator = xpath2.parse(req.query.name);
  nodes = evaluator.select({ node: doc });
  console.log('using const string - ', nodes[0].firstChild.data);
}

import xpath from 'xpath';
function myFunction2 (req, res) {
  var nodes;
  // ruleid:rules_lgpl_javascript_xml_rule-node-xpath-injection
  var evaluator = xpath.parse(req.query.name);
  nodes = evaluator.select({ node: doc });
  console.log('using const string - ', nodes[0].firstChild.data);
}

import xpath from 'xpath'
import { parse, useNamespaces, parse as pp, useNamespaces as un } from 'xpath'
function myFunction1 (req, res) {
  // ruleid:rules_lgpl_javascript_xml_rule-node-xpath-injection
  xpath.parse(req.query.name)
  // ruleid:rules_lgpl_javascript_xml_rule-node-xpath-injection
  parse(req.query.name)
  // ruleid:rules_lgpl_javascript_xml_rule-node-xpath-injection
  pp(req.query.name)
  // ok:rules_lgpl_javascript_xml_rule-node-xpath-injection
  xpath.useNamespaces(req.query.name)
  // ok:rules_lgpl_javascript_xml_rule-node-xpath-injection
  useNamespaces(req.query.name)
  // ok:rules_lgpl_javascript_xml_rule-node-xpath-injection
  un(req.query.name)
}

