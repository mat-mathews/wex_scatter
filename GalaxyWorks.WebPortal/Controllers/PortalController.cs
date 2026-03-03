using System;
using System.Threading.Tasks;
using System.Web.Mvc;
using GalaxyWorks.Data.DataServices;
using GalaxyWorks.Data.Models;
using GalaxyWorks.WebPortal.Models;

namespace GalaxyWorks.WebPortal.Controllers
{
    [Authorize]
    public class PortalController : BaseController
    {
        private readonly PortalDataService _portalDataService;

        public PortalController()
        {
            _portalDataService = new PortalDataService();
        }

        [HttpGet]
        public async Task<ActionResult> Index()
        {
            LogAction("PortalIndex");
            var config = await _portalDataService.RetrievePortalConfigurationAsync(1);

            if (config == null)
            {
                return View("NotConfigured");
            }

            var viewModel = new PortalConfigViewModel
            {
                ConfigurationId = config.ConfigurationId,
                PortalName = config.PortalName,
                EnableNotifications = config.EnableNotifications,
                MaxUsers = config.MaxUsers,
                LastUpdated = config.LastUpdated
            };

            return View(viewModel);
        }

        [HttpPost]
        [ValidateAntiForgeryToken]
        public async Task<ActionResult> Save(PortalConfigEditModel model)
        {
            if (!ModelState.IsValid)
            {
                return View("Edit", model);
            }

            try
            {
                LogAction("PortalSave");
                var entity = new PortalConfiguration
                {
                    ConfigurationId = model.ConfigurationId,
                    PortalName = model.PortalName,
                    EnableNotifications = model.EnableNotifications,
                    MaxUsers = model.MaxUsers
                };

                await _portalDataService.UpdatePortalConfigurationAsync(entity);
                TempData["SuccessMessage"] = "Portal configuration saved.";
                return RedirectToAction("Index");
            }
            catch (Exception ex)
            {
                return HandleError(ex);
            }
        }

        [HttpGet]
        public ActionResult Create()
        {
            return View(new PortalConfigEditModel());
        }
    }
}
