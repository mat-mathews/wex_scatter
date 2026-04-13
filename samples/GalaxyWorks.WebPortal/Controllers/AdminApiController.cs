using System.Threading.Tasks;
using System.Web.Mvc;
using GalaxyWorks.Data.DataServices;
using GalaxyWorks.Data.Models;

namespace GalaxyWorks.WebPortal.Controllers
{
    [Route("api/admin")]
    [Authorize(Roles = "Administrator")]
    public sealed class AdminApiController : BaseController
    {
        private readonly PortalDataService _dataService;

        public AdminApiController()
        {
            _dataService = new PortalDataService();
        }

        [HttpGet]
        [Route("module/{moduleName}")]
        public async Task<ActionResult> GetModule(string moduleName)
        {
            LogAction($"GetModule:{moduleName}");
            SystemModule module = await _dataService.GetSystemModuleDetailsAsync(moduleName);

            if (module == null)
            {
                return HttpNotFound();
            }

            return Json(module, JsonRequestBehavior.AllowGet);
        }

        [HttpGet]
        [Route("config/{id:int}")]
        public async Task<ActionResult> GetConfiguration(int id)
        {
            LogAction($"GetConfiguration:{id}");
            PortalConfiguration config = await _dataService.RetrievePortalConfigurationAsync(id);

            if (config == null)
            {
                return HttpNotFound();
            }

            return Json(config, JsonRequestBehavior.AllowGet);
        }
    }
}
