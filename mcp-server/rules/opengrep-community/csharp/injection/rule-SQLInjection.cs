// License: LGPL-3.0 License (c) security-code-scan
using System.Data.Entity;
using System.Data.Entity.Core.EntityClient;
using System.Data.Odbc;
using System.Data.OleDb;
using System.Data.SqlClient;
using MySql.Data.MySqlClient;
using Npgsql;
using Oracle.ManagedDataAccess.Client;
using Cassandra;
using System.Data.Linq;

class SQLInjection
{
    static void QueryWithUserInput(DbContext ctx, string input)
    {
        var cmd = "SELECT * FROM Users WHERE username = '" + input + "' and role='user'";
        // ruleid: csharp_injection_rule-SQLInjection
        ctx.Database.ExecuteSqlCommand(cmd);
        // ruleid: csharp_injection_rule-SQLInjection
        ctx.Database.ExecuteSqlCommandAsync(cmd);
        // ruleid: csharp_injection_rule-SQLInjection
        var items = db.Database.SqlQuery<Items>(cmd).ToList();
        var safecmd = "SELECT * FROM Users"
        // ok: csharp_injection_rule-SQLInjection
        var items = db.Database.SqlQuery<Items>(safecmd).ToList();
    }

    static void QueryTwoWithUserInput(string input)
    {
        // Define the connection string
        string connectionString = "Data Source=.;Initial Catalog=YourDatabase;Integrated Security=True";
        DataContext dbContext = new DataContext(connectionString);
        string sqlQuery = "SELECT * FROM Users WHERE username = '" + input + "' and role='user'";
        
        // ruleid: csharp_injection_rule-SQLInjection
        var result = dbContext.ExecuteQuery<User>(sqlQuery);

        // ruleid: csharp_injection_rule-SQLInjection
        var results = dbContext.ExecuteQuery(typeof(object), sqlQuery);

        // Define a raw SQL command to update user age
        string updateCommand = "UPDATE Users SET Age = {0} WHERE Id = '" + input + "'";

        // ruleid: csharp_injection_rule-SQLInjection
        int rowsAffected = dbContext.ExecuteCommand(updateCommand, 35);

        string safeCommand = "UPDATE Users SET Age = {0} WHERE Id = {1}" ;
        // ok: csharp_injection_rule-SQLInjection
        int rows = dbContext.ExecuteCommand(safeCommand, 35, 1);
    }

    static void QueryWithUserInputSqlClient(string input)
    {
        // ruleid: csharp_injection_rule-SQLInjection
        var cmd = new SqlCommand("SELECT * FROM Users WHERE username = '" + input + "' and role='user'");
        cmd.ExecuteReader();
    }

    static void QueryWithUserInputCommandText(string input)
    {
        SqlCommand sqlCmd = new SqlCommand();
        // ruleid: csharp_injection_rule-SQLInjection
        sqlCmd.CommandText = "SELECT * FROM Users WHERE username = '" + input + "' and role='user'";
        sqlCmd.CommandText = "abc";
        sqlCmd.ExecuteReader();

        var oracleCmd = new OracleCommand();
        // ruleid: csharp_injection_rule-SQLInjection
        oracleCmd.CommandText = "SELECT * FROM Users WHERE username = '" + input + "' and role='user'";
        oracleCmd.CommandText = "abc";
        oracleCmd.ExecuteReader();

        var npgsqlCmd = new NpgsqlCommand();
        // ruleid: csharp_injection_rule-SQLInjection
        npgsqlCmd.CommandText = "SELECT * FROM Users WHERE username = '" + input + "' and role='user'";
        npgsqlCmd.CommandText = "abc";
        npgsqlCmd.ExecuteReader();

        var mySqlCmd = new MySqlCommand();
        // ruleid: csharp_injection_rule-SQLInjection
        mySqlCmd.CommandText = "SELECT * FROM Users WHERE username = '" + input + "' and role='user'";
        mySqlCmd.CommandText = "abc";
        mySqlCmd.ExecuteReader();

        var entityCmd = new EntityCommand();
        // ruleid: csharp_injection_rule-SQLInjection
        entityCmd.CommandText = "SELECT * FROM Users WHERE username = '" + input + "' and role='user'";
        entityCmd.CommandText = "abc";
        entityCmd.ExecuteReader();

        OdbcCommand odbcCmd = new OdbcCommand();
        // ruleid: csharp_injection_rule-SQLInjection
        odbcCmd.CommandText = "SELECT * FROM Users WHERE username = '" + input + "' and role='user'";
        odbcCmd.CommandText = "abc";
        odbcCmd.ExecuteReader();

        var oleDbCmd = new OleDbCommand();
        // ruleid: csharp_injection_rule-SQLInjection
        oleDbCmd.CommandText = "SELECT * FROM Users WHERE username = '" + input + "' and role='user'";
        oleDbCmd.CommandText = "abc";
        oleDbCmd.ExecuteReader();

        // Check with formatted strings too.
        // ruleid: csharp_injection_rule-SQLInjection
        oleDbCmd.CommandText = String.Format("SELECT * FROM Users WHERE username = '{0}' and role='user'", input);
        oleDbCmd.ExecuteReader();
    }

    static void SafeSanitized(DbContext ctx, string input)
    {
        var cmd = "SELECT * FROM Users WHERE username = @username and role='user'";
        // ok: csharp_injection_rule-SQLInjection
        ctx.Database.ExecuteSqlCommand(
            cmd,
            new SqlParameter("@username", input));
    }

    static void SafeConstant(DbContext ctx)
    {
        var cmd = "SELECT * FROM Users";
        // ok: csharp_injection_rule-SQLInjection
        ctx.Database.ExecuteSqlCommand(cmd);
    }

    static void SafeConstantSqlClient()
    {
        // ok: csharp_injection_rule-SQLInjection
        var cmd = new SqlCommand("SELECT * FROM Users");
        cmd.ExecuteReader();
    }

    static void SafeSanitizedSqlClient(string input)
    {
        // ok: csharp_injection_rule-SQLInjection
        var cmd = new SqlCommand("SELECT * FROM Users WHERE username = '@username' and role='user'");
        cmd.Parameters.AddWithValue("@username", input);
        cmd.Parameters["@username"].Value = input;
        cmd.ExecuteReader();
    }
        
    static void exampleMySqlClient(string input)
    {
        var cmd = "SELECT * FROM Users WHERE username = '" + input + "' and role='user'";
        // ruleid: csharp_injection_rule-SQLInjection
        var dtRow = MySqlHelper.ExecuteDataRow(Connection.ConnectionStr, cmd);
        var cmd = "SELECT * FROM Users WHERE username = 'abc' and role='user'";
        // ok: csharp_injection_rule-SQLInjection
        var dtRow = MySqlHelper.ExecuteDataRow(Connection.ConnectionStr, cmd);

    }

    static void exampleCassandra(string userInput)
    {
        var cluster=Cluster.Builder().AddContactPoint("127.0.0.1").Build();
        var session=cluster.Connect("test_keyspace");
        string query="SELECT * FROM users WHERE id="+userInput;
        // ruleid: csharp_injection_rule-SQLInjection
        session.Execute(query);
        query = "SELECT * FROM Users WHERE username = 'abc' and role='user'";
        // ok: csharp_injection_rule-SQLInjection
        session.Execute(query);
    }
}
