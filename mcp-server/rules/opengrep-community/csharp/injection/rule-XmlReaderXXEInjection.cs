// License: LGPL-3.0 License (c) security-code-scan
using System.Xml;

namespace consoleAppDNF4.CSharp.Injection
{
    internal class XXEInjection : IScenarioRunner
    {
        private void TestReaderSettings(string path)
        {
            try
            {
                var settings = new XmlReaderSettings();
                settings.ProhibitDtd = false;
                settings.DtdProcessing = DtdProcessing.Parse;

                // ruleid: csharp_injection_rule-XmlReaderXXEInjection
                XmlReader reader = XmlReader.Create(path, settings);

                while (reader.Read())
                {
                    if (reader.NodeType == XmlNodeType.Element)
                    {
                        Console.WriteLine("Inner XML: " + reader.ReadInnerXml());
                    }
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine(ex.Message.ToString());
            }
        }

        private void TestReaderSettings2(string path)
        {
            try
            {
                var settings = new XmlReaderSettings();
                settings.DtdProcessing = DtdProcessing.Prohibit;

                // ok: csharp_injection_rule-XmlReaderXXEInjection
                XmlReader reader = XmlReader.Create(path, settings);

                while (reader.Read())
                {
                    if (reader.NodeType == XmlNodeType.Element)
                    {
                        Console.WriteLine("Inner XML: " + reader.ReadInnerXml());
                    }
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine(ex.Message.ToString());
            }
        }

        private void TestReaderSettingsSafe(string path)
        {
            try
            {
                var settings = new XmlReaderSettings();
                settings.ProhibitDtd = false;

                // ruleid: csharp_injection_rule-XmlReaderXXEInjection
                XmlReader reader = XmlReader.Create(path, settings);

                while (reader.Read())
                {
                    if (reader.NodeType == XmlNodeType.Element)
                    {
                        Console.WriteLine("Inner XML: " + reader.ReadInnerXml());
                    }
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine(ex.Message.ToString());
            }
        }

        private void TestReaderWithoutSettings(string path)
        {
            try
            {
                // ok: csharp_injection_rule-XmlReaderXXEInjection
                XmlReader reader = XmlReader.Create(path);

                while (reader.Read())
                {
                    if (reader.NodeType == XmlNodeType.Element)
                    {
                        Console.WriteLine("Inner XML: " + reader.ReadInnerXml());
                    }
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine(ex.Message.ToString());
            }
        }   
    }
}


