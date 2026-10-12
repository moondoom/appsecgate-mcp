// License: LGPL-3.0 License (c) security-code-scan

using System.Xml;
using System.Xml.Linq;
using System.Xml.Schema;
using System.Xml.XPath;

class XPathInjection
{
    static void QueryWithUserInput()
    {
        var input = Console.ReadLine();
        var doc = new XmlDocument {XmlResolver = null};
        doc.Load("/config.xml");
        
        // ruleid: csharp_injection_rule-XPathInjection
        var results = doc.SelectNodes("/Config/Devices/Device[id='" + input + "']");

        // ruleid: csharp_injection_rule-XPathInjection
        var result = doc.SelectSingleNode("/Config/Devices/Device[id='" + input + "']")!;

        result.SelectSingleNode("/Config/Devices/Device[id='" + input + "']");

        XPathNavigator navigator = doc.CreateNavigator()!;
        // ruleid: csharp_injection_rule-XPathInjection
        navigator.Compile(input);
        // ruleid: csharp_injection_rule-XPathInjection
        navigator.Evaluate(input);
        // ruleid: csharp_injection_rule-XPathInjection
        navigator.Matches(input);
        // ruleid: csharp_injection_rule-XPathInjection
        navigator.Select(input);
        // ruleid: csharp_injection_rule-XPathInjection
        navigator.SelectAncestors(input, input, false);
        // ruleid: csharp_injection_rule-XPathInjection
        navigator.SelectChildren(input, input);
        // ruleid: csharp_injection_rule-XPathInjection
        navigator.SelectDescendants(input, input, false);
        // ruleid: csharp_injection_rule-XPathInjection
        navigator.SelectSingleNode(input);
    }

    static void LinqExtensionQueryWithUserInput()
    {
        var input = Console.ReadLine();
        XDocument d = XDocument.Parse("");  
        // ruleid: csharp_injection_rule-XPathInjection
        d.XPathEvaluate("/root/" + input);  
        // ruleid: csharp_injection_rule-XPathInjection
        d.XPathSelectElement("/root/" + input);  
        // ruleid: csharp_injection_rule-XPathInjection
        d.XPathSelectElements("/root/" + input);  
    }

    static void XPathWithUserInput()
    {
        var input = Console.ReadLine();
        XmlSchemaXPath path = new XmlSchemaXPath
        {
            // ruleid: csharp_injection_rule-XPathInjection
            XPath = input
        };

        var path2 = new XmlSchemaXPath();
        // ruleid: csharp_injection_rule-XPathInjection
        path2.XPath = input;
    }

    static void Safe()
    {
        var doc = new XmlDocument {XmlResolver = null};
        doc.Load("/config.xml");

        var results = doc.SelectNodes("/Config/Devices/Device[id='123']");

        XmlNode result = doc.SelectSingleNode("/Config/Devices/Device[id='123']")!;

        result.SelectSingleNode("/Config/Devices/Device[id='123']");
        
        XDocument d = XDocument.Parse("");
        d.XPathEvaluate("/root");
        d.XPathSelectElement("/root");
        d.XPathSelectElements("/root");

        var cookieParameterNames = new HashSet<string>(cookieParameters.Select(c => c.Name));
    }
}
