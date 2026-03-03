using System;
using System.Web.Mvc;

namespace GalaxyWorks.WebPortal.Controllers
{
    public abstract class BaseController : Controller
    {
        protected virtual string CurrentUserName
        {
            get { return User?.Identity?.Name ?? "Anonymous"; }
        }

        protected virtual ActionResult HandleError(Exception ex, string viewName = "Error")
        {
            ViewBag.ErrorMessage = ex.Message;
            return View(viewName);
        }

        protected virtual void LogAction(string action)
        {
            System.Diagnostics.Debug.WriteLine($"[{DateTime.UtcNow:O}] User={CurrentUserName} Action={action}");
        }

        protected override void OnActionExecuting(ActionExecutingContext filterContext)
        {
            ViewBag.CurrentUser = CurrentUserName;
            base.OnActionExecuting(filterContext);
        }
    }
}
