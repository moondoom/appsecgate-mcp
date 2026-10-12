// License: LGPL-3.0 License (c) security-code-scan
using System.Xml;

namespace consoleAppDNF4.CSharp.Injection
{
    internal class XXEInjection : IScenarioRunner
    {
        private void TestXMlDocument(string path)
        {
            try
            {
                XmlDocument xmlDocUnSafe = new XmlDocument();
                // ruleid: csharp_injection_rule-XmlDocumentXXEInjection
                xmlDocUnSafe.Load(path);
                Console.WriteLine(xmlDocUnSafe.InnerText);

                XmlDocument xmlDocSafe = new XmlDocument();
                xmlDocSafe.XmlResolver = null;
                // ok: csharp_injection_rule-XmlDocumentXXEInjection
                xmlDocSafe.Load(path);
                Console.WriteLine(xmlDocSafe.InnerText);
            }
            catch (Exception ex)
            {
                Console.WriteLine(ex.Message.ToString());
            }
        }

        private void TestXMlDocument2(string path)
        {
            string xxePayload = $"<!DOCTYPE doc [<!ENTITY win SYSTEM '{path}'>]>"
                     + "<doc>&win;</doc>";
            string xml = "<?xml version='1.0' ?>" + xxePayload;

            try
            {
                XmlDocument xmlDocUnSafe = new XmlDocument();
                // ruleid: csharp_injection_rule-XmlDocumentXXEInjection
                xmlDocUnSafe.LoadXml(xml);
                Console.WriteLine("with Resolver " + xmlDocUnSafe.InnerText);

                XmlDocument xmlDocSafe = new XmlDocument();
                xmlDocSafe.XmlResolver = null;
                // ok: csharp_injection_rule-XmlDocumentXXEInjection
                xmlDocSafe.LoadXml(xml);
                Console.WriteLine("null Resolver " + xmlDocSafe.InnerText);
            }
            catch (Exception ex)
            {
                Console.WriteLine(ex.Message.ToString());
            }
        }
    }
}