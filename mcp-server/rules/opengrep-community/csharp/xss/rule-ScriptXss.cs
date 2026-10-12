// License: LGPL-3.0 License (c) security-code-scan
using System;
using System.Text;
using System.Web;
using System.Web.Security.AntiXss;
using System.Web.UI;

namespace donNetWebFormPages.Views.Injection
{
    // ref: csharp_xss_rule-ScriptXss
    public partial class xss : Page
    {
        // sample url: http://172.21.153.221/Views/Injection/xss?quary=alert(%27a%27)
        protected void Page_Load(object sender, EventArgs e)
        {
            string name = Request.QueryString["quary"];
            StringBuilder cstext2 = new StringBuilder();
            cstext2.Append("<script type=\"text/javascript\">");
            cstext2.Append(name + "</");
            cstext2.Append("script>");
            // ruleid: csharp_xss_rule-ScriptXss
            RegisterClientScriptBlock("block", cstext2.ToString());
            // ruleid: csharp_xss_rule-ScriptXss
            RegisterStartupScript("Startup", cstext2.ToString());

            Response.AddHeader("Alert-Header", "alert('From AddHeader')");
            Response.AppendHeader("Alert-Header2", "alert('From AppendHeader')");

            // ok: csharp_xss_rule-ScriptXss
            Response.Write("<script>alert('From Write')</script>");
        }

        protected void onBtnSubmitClk(object sender, EventArgs e)
        {
            string script = txtInput.Text;
            // ruleid: csharp_xss_rule-ScriptXss
            ScriptManager.RegisterStartupScript(Page, typeof(Page), "StartupScript", script, true);
            lblOutput.Text = "You entered: " + script;
        }

        protected void onBtnSubmitClk1(object sender, EventArgs e)
        {
            string script = txtInput.Text;
            // ruleid: csharp_xss_rule-ScriptXss
            ScriptManager.RegisterStartupScript(Page, typeof(Page), "StartupScript", script, true);
            ClientScriptManager cs = Page.ClientScript;
            StringBuilder cstext1 = new StringBuilder();
            cstext1.Append("<script type=text/javascript> " + script + " </");
            cstext1.Append("script>");
            // ruleid: csharp_xss_rule-ScriptXss
            cs.RegisterStartupScript(this.GetType(), "csname1", cstext1.ToString());
            // ruleid: csharp_xss_rule-ScriptXss
            cs.RegisterClientScriptBlock(this.GetType(), "csname2", cstext1.ToString());
            lblOutput.Text = "You entered: " + script;
        }

        protected void onBtnSubmitClkHE(object sender, EventArgs e)
        {
            string script = HttpUtility.HtmlEncode(txtInput.Text);
            ScriptManager.RegisterStartupScript(Page, typeof(Page), "StartupScript", script, true);
            ClientScriptManager cs = Page.ClientScript;
            StringBuilder cstext1 = new StringBuilder();
            cstext1.Append("<script type=text/javascript> " + script + " </");
            cstext1.Append("script>");
            // ok: csharp_xss_rule-ScriptXss
            cs.RegisterStartupScript(this.GetType(), "csname1", cstext1.ToString());
            // ok: csharp_xss_rule-ScriptXss
            cs.RegisterClientScriptBlock(this.GetType(), "csname2", cstext1.ToString());
            lblOutput.Text = "You entered: " + script;
        }

        protected void onBtnSubmitClkHAE(object sender, EventArgs e)
        {
            string script = HttpUtility.HtmlAttributeEncode(txtInput.Text);
            ScriptManager.RegisterStartupScript(Page, typeof(Page), "StartupScript", script, true);
            ClientScriptManager cs = Page.ClientScript;
            StringBuilder cstext1 = new StringBuilder();
            cstext1.Append("<script type=text/javascript> " + script + " </");
            cstext1.Append("script>");
            // ok: csharp_xss_rule-ScriptXss
            cs.RegisterStartupScript(this.GetType(), "csname1", cstext1.ToString());
            // ok: csharp_xss_rule-ScriptXss
            cs.RegisterClientScriptBlock(this.GetType(), "csname2", cstext1.ToString());
            lblOutput.Text = "You entered: " + script;
        }

        protected void onBtnSubmitClkHFUE(object sender, EventArgs e)
        {
            string script = AntiXssEncoder.HtmlFormUrlEncode(txtInput.Text);
            ScriptManager.RegisterStartupScript(Page, typeof(Page), "StartupScript", script, true);
            ClientScriptManager cs = Page.ClientScript;
            StringBuilder cstext1 = new StringBuilder();
            cstext1.Append("<script type=text/javascript> " + script + " </");
            cstext1.Append("script>");
            // ok: csharp_xss_rule-ScriptXss
            cs.RegisterStartupScript(this.GetType(), "csname1", cstext1.ToString());
            // ok: csharp_xss_rule-ScriptXss
            cs.RegisterClientScriptBlock(this.GetType(), "csname2", cstext1);
            lblOutput.Text = "You entered: " + script;
        }
    }
}