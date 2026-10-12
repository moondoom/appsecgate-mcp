// License: LGPL-3.0 License (c) security-code-scan
using System;
using System.IO;
using System.Web;
using System.Web.Mvc;
using System.Web.Optimization;
using System.Web.UI;
using System.Web.WebPages;

// ref: csharp_xss_rule-HtmlElementXss
namespace dotNetFrameworkWebApp.Controllers.XSS
{
    public class XssController : Controller
    {
        // sample: http://172.21.156.246/xss/WriteHtml
        public object WriteHtml(string alert)
        {
            string qs = Request.QueryString["alert"];
            string form = Request.Form["alert"];
            string headers = Request.Headers[0];
            string paras = Request.Params["alert"];
            string path = Request.Path;
            string rawURL = Request.RawUrl;
            string URL = Request.Url.ToString();

            StringWriter stringWriter = new StringWriter();

            HtmlTextWriter writer = new HtmlTextWriter(stringWriter);

            // ruleid: csharp_xss_rule-HtmlElementXss
            writer.Write($"QueryString: {qs} <br/>");

            // ok: csharp_xss_rule-HtmlElementXss
            writer.Write(HttpUtility.HtmlEncode("<script>" + alert + "('From HtmlTextWriter WriteFullBeginTag')</script>"));

            string sanitize = HttpUtility.HtmlEncode("<script>" + form + "('From HtmlTextWriter WriteFullBeginTag')</script>");
            // ok: csharp_xss_rule-HtmlElementXss
            writer.WriteFullBeginTag(sanitize);

            // ruleid: csharp_xss_rule-HtmlElementXss
            writer.Write("<script>" + headers.Substring(0, 1) + "('From HtmlTextWriter Write')</script>");

            // ruleid: csharp_xss_rule-HtmlElementXss
            writer.WriteBeginTag("<script>" + paras + "('From HtmlTextWriter WriteBeginTag')</script>");

            // ruleid: csharp_xss_rule-HtmlElementXss
            writer.WriteEndTag("<script><script>" + path + "('From HtmlTextWriter WriteEndTag')</script></script>");

            writer.EndRender();

            // ruleid: csharp_xss_rule-HtmlElementXss
            writer.AddAttribute(HtmlTextWriterAttribute.Width, "\"><script>" + rawURL + "('From HtmlTextWriter AddAttribute')</script>");
            writer.RenderBeginTag(HtmlTextWriterTag.Span);
            writer.Write("Content inside the span");
            writer.RenderEndTag();

            // ok: csharp_xss_rule-HtmlElementXss
            writer.RenderBeginTag(HtmlTextWriterTag.Div);
            // ruleid: csharp_xss_rule-HtmlElementXss
            writer.WriteAttribute("class", "''><script>" + URL.Split('/')[0] + "('From HtmlTextWriter WriteAttribute')</script>");
            writer.RenderEndTag();

            writer.RenderBeginTag(HtmlTextWriterTag.Div);
            // ruleid: csharp_xss_rule-HtmlElementXss
            writer.AddStyleAttribute("color", "\"><script>" + alert + "('From HtmlTextWriter AddStyleAttribute')</script>");
            writer.EndRender();

            writer.RenderBeginTag(HtmlTextWriterTag.Div);
            // ruleid: csharp_xss_rule-HtmlElementXss
            writer.WriteStyleAttribute("color", "\"><script>" + alert + "('From HtmlTextWriter WriteStyleAttribute')</script>");
            writer.EndRender();

            writer.Flush();
            return Content(stringWriter.ToString(), "text/html");
        }
    }

    public ActionResult createRaw(string alert)
    {
        string dynamicContent = "<script>" + alert + "('From SendEmail')</script>";
        var htmlHelper = new HtmlHelper(new ViewContext(), new ViewPage());
        // ruleid: csharp_xss_rule-HtmlElementXss
        var rawHtml = htmlHelper.Raw(dynamicContent).ToHtmlString();

        // ruleid: csharp_xss_rule-HtmlElementXss
        Response.Write(rawHtml);
        return Content("Alert shown from htmlHelper.Raw");
    }

    public string directReturn(string alert)
    {
        return "<script>" + alert + "('From SendEmail')</script>";
    }
}