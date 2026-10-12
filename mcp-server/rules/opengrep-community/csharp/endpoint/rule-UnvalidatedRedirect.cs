// License: LGPL-3.0 License (c) security-code-scan
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using System.Collections.Specialized;


namespace dotNetMVC.Controllers.Endpoint
{
    // ref: csharp_endpoint_rule-UnvalidatedRedirect
    public class UnvalidatedRedirectController : Controller
    {

        // GET: UnvalidatedRedirectController
        public ActionResult Index()
        {
            return View("Views/Endpoint/UnvalidatedRedirect/index.cshtml");
        }

        [HttpGet]
        public IActionResult LogOn(string returnUrl)
        {
            if (!String.IsNullOrEmpty(returnUrl))
            {
                // ruleid: csharp_endpoint_rule-UnvalidatedRedirect
                return Redirect(returnUrl);
            }
            // ruleid: csharp_endpoint_rule-UnvalidatedRedirect
            return new RedirectResult(returnUrl);
        }

        [HttpGet]
        public IActionResult LogOn2(string returnUrl)
        {
            if (Url.IsLocalUrl(returnUrl))
            {
                // ok: csharp_endpoint_rule-UnvalidatedRedirect
                return RedirectPermanent(returnUrl);
            }
            // ruleid: csharp_endpoint_rule-UnvalidatedRedirect
            return RedirectPermanent(returnUrl);
        }

        [HttpGet]
        public IActionResult LogOnTryCreate(string returnUrl)
        {
            if (Uri.TryCreate(returnUrl, UriKind.Relative, out var result))
            {
                // ruleid: csharp_endpoint_rule-UnvalidatedRedirect
                return Redirect(result.ToString());
            }
            // ruleid: csharp_endpoint_rule-UnvalidatedRedirect
            return Redirect(returnUrl);
        }

        [HttpGet]
        // sample end point: https://localhost:7084/UnvalidatedRedirect/logonAction?at=TestPoint
        public IActionResult LogOnAction(string at)
        {
            string url = Url.Action(at, "Home");
            // ok: csharp_endpoint_rule-UnvalidatedRedirect
            return Redirect(url);
        }

        [HttpGet]
        // sample end point: https://localhost:7084/UnvalidatedRedirect/LogOnRouteUrl?at=TESTPoint
        public IActionResult LogOnRouteUrl(string at)
        {
            string url = Url.RouteUrl(at);
            // ok: csharp_endpoint_rule-UnvalidatedRedirect
            return Redirect(url);
        }
         
        // GET https://localhost:44355/UnvalidatedRedirect/Get?path=testPoint
        public ActionResult Get(string path)
        {
            string url = Url.HttpRouteUrl(path, null);
            // ok: csharp_endpoint_rule-UnvalidatedRedirect
            return Redirect(url);
        }
    }
}