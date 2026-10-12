// License: LGPL-3.0 License (c) security-code-scan
using System.Xml.Xsl;

class UnsafeXSLTSettingsUsed
{
    static void Unsafe()
    {
        XslCompiledTransform transform = new XslCompiledTransform();
        // ruleid: csharp_other_rule-UnsafeXSLTSettingUsed
        XsltSettings settings = new XsltSettings() {EnableScript = true};
        transform.Load("foo", settings, null);

        XslCompiledTransform transform = new XslCompiledTransform();
        // ruleid: csharp_other_rule-UnsafeXSLTSettingUsed
        XsltSettings settings = new XsltSettings() {EnableDocumentFunction = true};
        transform.Load("foo", settings, null);

        XslCompiledTransform transform = new XslCompiledTransform();
        // ruleid: csharp_other_rule-UnsafeXSLTSettingUsed
        XsltSettings settings = new XsltSettings() {EnableScript=false, EnableDocumentFunction = true};
        transform.Load(dd, settings, null);

        XslCompiledTransform transform = new XslCompiledTransform();
        // ruleid: csharp_other_rule-UnsafeXSLTSettingUsed
        XsltSettings settings = new XsltSettings() {EnableScript=true, EnableDocumentFunction = false};
        transform.Load("foo", settings, null);

        XsltSettings settings2 = new XsltSettings();
        // ruleid: csharp_other_rule-UnsafeXSLTSettingUsed
        settings2.EnableScript = true;
        transform.Load("foo", settings2, null);

        XsltSettings settings3 = new XsltSettings();
        // ruleid: csharp_other_rule-UnsafeXSLTSettingUsed
        settings3.EnableDocumentFunction = true;
        transform.Load("foo", settings3, null);
    }

    static void unSafeRead()
        {
            XmlDocument xmlDoc = new XmlDocument();
            xmlDoc.Load("docxml.xml");

            XslCompiledTransform xslt = new XslCompiledTransform();
            // ruleid: csharp_other_rule-UnsafeXSLTSettingUsed
            xslt.Load("docxsl.xslt", new XsltSettings() { EnableDocumentFunction = true }, null);
    }

    static void Safe()
    {
        XslCompiledTransform transform = new XslCompiledTransform();
        // ok: csharp_other_rule-UnsafeXSLTSettingUsed
        XsltSettings settings = new XsltSettings();
        transform.Load("foo", settings, null); 
    }
}