// License: GNU Lesser General Public License v3.0
// source (original): https://github.com/ajinabraham/njsscan/blob/master/tests/assets/node_source/true_positives/semantic_grep/database/sequelize_tls_validation.js
// hash: e7a0a61
// Example for mysql
module.exports = {

    // ruleid: rules_lgpl_javascript_database_rule-sequelize-tls-cert-validation
    dev: {
        username: "0xdbe",
        database: "app_db",
        dialect: "mariadb",
        host: "127.0.0.1",
        dialectOptions: {
        ssl: {
            rejectUnauthorized: false
        }
        }
    }
    };
    // Example for mysql
    module.exports = {
    
    // ruleid: rules_lgpl_javascript_database_rule-sequelize-tls-cert-validation
    dev: {
        username: "0xdbe",
        database: "app_db",
        dialect: "mysql",
        host: "127.0.0.1",
        dialectOptions: {
        ssl: {
            rejectUnauthorized: false
        }
        }
    }
    };
    
    
    // Example for postgresql
    module.exports = {
    
    // ruleid: rules_lgpl_javascript_database_rule-sequelize-tls-cert-validation
    dev: {
        username: "0xdbe",
        database: "app_db",
        dialect: "postgres",
        host: "127.0.0.1",
        dialectOptions: {
        ssl: {
            rejectUnauthorized: false
        }
        }
    }
    };
    