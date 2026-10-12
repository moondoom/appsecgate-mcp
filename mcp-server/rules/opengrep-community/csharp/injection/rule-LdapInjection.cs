// License: LGPL-3.0 License (c) security-code-scan

using System.DirectoryServices;
using System.DirectoryServices.AccountManagement;
using System.DirectoryServices.Protocols;
using System.Net;

// ref: csharp_injection_rule-LdapInjection
namespace consoleApp.cSharp.Injection
{
    internal class LdapInjection : IScenarioRunner
    {
        string ldapserver = "127.0.0.1:3889";
        string ldapbasedn = "dc=example,dc=org";
        string ldapuser = "cn=admin,dc=example,dc=org";
        string ldappassword = "adminpassword";

        public void SentReqTest(string classname)
        {
            try
            {
                using var ldapConnection = new LdapConnection(new LdapDirectoryIdentifier("127.0.0.1", 3889), new NetworkCredential("cn=admin,dc=example,dc=org", "adminpassword"), AuthType.Basic);
                ldapConnection.SessionOptions.ProtocolVersion = 3;
                ldapConnection.Bind();

                string baseDn = "dc=example,dc=org";
                string filter = $"(objectClass={classname})";

                // ruleid: csharp_injection_rule-LdapInjection
                SearchRequest searchReq = new SearchRequest(
                    baseDn,
                    filter,
                    System.DirectoryServices.Protocols.SearchScope.Subtree,
                    null
                );

                SearchResponse searchRes = (SearchResponse)ldapConnection.SendRequest(searchReq);

                foreach (SearchResultEntry en in searchRes.Entries)
                {
                    foreach (DirectoryAttribute att in en.Attributes.Values)
                    {
                        Console.WriteLine($"{att.Name}: {att[0]}");
                    }

                    Console.WriteLine("******");
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine(ex.ToString());
            }

            Console.WriteLine("\n***End SentReqTest***\n");
        }

        public void UseDirectorySearcherFilterTest(string classname)
        {
            string ldapfilter = $"(objectClass={classname})";

            try
            {
                string DN = "";
                using (DirectoryEntry entry = new DirectoryEntry("LDAP://" + ldapserver + "/" + ldapbasedn, ldapuser, ldappassword, AuthenticationTypes.None))
                {
                    entry.Path = "LDAP://" + ldapserver + "/" + ldapbasedn;

                    DirectorySearcher ds = new DirectorySearcher(entry);
                    ds.SearchScope = System.DirectoryServices.SearchScope.Subtree;

                    // ok: csharp_injection_rule-LdapInjection
                    ds.Filter = "(objectClass=*)";
                    // ruleid: csharp_injection_rule-LdapInjection
                    ds.Filter = $"(objectClass={classname})";

                    SearchResult result = ds.FindOne();
                    
                    if (result != null)
                    {
                        foreach (string propertyName in result.Properties.PropertyNames)
                        {
                            Console.WriteLine($"{propertyName}: {result.Properties[propertyName][0]}");
                        }
                    }
                }
            }
            catch (Exception ex) {
                Console.WriteLine(ex.Message);
            }

            Console.WriteLine("\n*** End UseDirectorySearcherPathTest ***\n");
        }

        public void UseDirectorySearcherPathTest(string pathPara)
        {
            string ldapfilter = "(objectClass=*)";

            try
            {
                using (DirectoryEntry entry = new DirectoryEntry("LDAP://" + ldapserver + "/" + ldapbasedn, ldapuser, ldappassword, AuthenticationTypes.None))
                {
                    // ruleid: csharp_injection_rule-LdapInjection
                    entry.Path = "LDAP://" + ldapserver + "/" + pathPara;

                    // ruleid: csharp_injection_rule-LdapInjection
                    DirectorySearcher ds = new DirectorySearcher(entry);
                    ds.SearchScope = System.DirectoryServices.SearchScope.Subtree;

                    // ok: csharp_injection_rule-LdapInjection
                    ds.Filter = string.Format(ldapfilter);

                    SearchResult result = ds.FindOne();

                    if (result != null)
                    {
                        foreach (string propertyName in result.Properties.PropertyNames)
                        {
                            Console.WriteLine($"{propertyName}: {result.Properties[propertyName][0]}");
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine(ex.Message);
            }

            Console.WriteLine("\n***End UseDirectorySearcherPathTest***\n");
        }

        public void UserPrincipleTest(string samAccountName)
        {
            try
            {
                PrincipalContext context = new PrincipalContext(ContextType.Machine);
                UserPrincipal userPrincipal = new UserPrincipal(context);

                // ruleid: csharp_injection_rule-LdapInjection
                userPrincipal.SamAccountName = samAccountName;

                // ruleid: csharp_injection_rule-LdapInjection
                UserPrincipal.FindByIdentity(context, samAccountName);

                using (PrincipalSearcher searcher = new PrincipalSearcher(userPrincipal))
                {
                    PrincipalSearchResult<Principal> foundUser = searcher.FindAll() as PrincipalSearchResult<Principal>;

                    if (foundUser != null)
                    {
                        foreach (var item in foundUser.AsQueryable().ToArray())
                        {
                            Console.WriteLine(item.SamAccountName.ToString());
                        };
                    }
                    else
                    {
                        Console.WriteLine("User not found.");
                    }
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine(ex);
            }

            Console.WriteLine("\n***End UserPrincipleTest***\n");
        }
    }
}
