// License: GNU Lesser General Public License v3.0
// source (original): https://github.com/ajinabraham/njsscan/blob/master/tests/assets/node_source/true_positives/semantic_grep/database/sequelize_tls.js
// hash: e7a0a61
module.exports = {
    // ruleid: rules_lgpl_javascript_database_rule-sequelize-tls
    local: {
      username: "AppUser",
      database: "AppDb",
      dialect: "postgres",
      host: "127.0.0.1"
    }
  };
  
  module.exports = {
  // ruleid: rules_lgpl_javascript_database_rule-sequelize-tls
  local: {
    username: "AppUser",
    database: "AppDb",
    dialect: "mariadb",
    host: "127.0.0.1"
  }
  };
  
  module.exports = {
  // ruleid: rules_lgpl_javascript_database_rule-sequelize-tls
  local: {
    username: "AppUser",
    database: "AppDb",
    dialect: "mysql",
    host: "127.0.0.1"
  }
  };
  
  module.exports = {
  // ruleid: rules_lgpl_javascript_database_rule-sequelize-tls
  local: {
    username: "AppUser",
    database: "AppDb",
    dialect: "postgres",
    host: "127.0.0.1",
    dialectOptions: {
    ssl: false
    }
  }
  };