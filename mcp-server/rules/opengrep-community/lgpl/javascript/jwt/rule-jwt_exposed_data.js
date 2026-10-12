// License: GNU Lesser General Public License v3.0
// source (original): https://github.com/ajinabraham/njsscan/blob/master/tests/assets/node_source/true_positives/semantic_grep/jwt/jwt_exposed_data.js
// hash: e7a0a61
const config = require('./config')
const { JWT } = require('jose')

function example(user) {
    // ruleid: rules_lgpl_javascript_jwt_rule-jwt-exposed-data
    const token = JWT.sign(user, secret)
    return token;
}