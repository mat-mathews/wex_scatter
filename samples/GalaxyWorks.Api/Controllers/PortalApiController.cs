// Tests: ASP.NET Core patterns — ControllerBase, [ApiController], [Route].
// Also tests: file-scoped namespace, using alias, using static.
// No per-file `using GalaxyWorks.Data.*` — relies on GlobalUsings.cs.

using DataSvc = GalaxyWorks.Data.DataServices.PortalDataService;
using static GalaxyWorks.Data.Models.StatusType;

using Microsoft.AspNetCore.Mvc;

namespace GalaxyWorks.Api.Controllers;

[ApiController]
[Route("api/[controller]")]
public class PortalApiController : ControllerBase
{
    // Tests: using alias — Scatter won't see "PortalDataService" at usage sites
    private readonly DataSvc _dataService;

    public PortalApiController()
    {
        _dataService = new DataSvc();
    }

    [HttpGet("config/{adminId}")]
    public async Task<ActionResult<Result<PortalConfiguration>>> GetConfiguration(int adminId)
    {
        var config = await _dataService.RetrievePortalConfigurationAsync(adminId);
        if (config == null)
            return NotFound(Result.Fail("Configuration not found"));

        return Ok(Result<PortalConfiguration>.Ok(config));
    }

    [HttpPost("config")]
    public async Task<ActionResult<Result<int>>> CreateConfiguration([FromBody] PortalConfiguration config)
    {
        var id = await _dataService.StorePortalConfigurationAsync(config);
        return CreatedAtAction(nameof(GetConfiguration), new { adminId = id }, Result<int>.Ok(id));
    }

    [HttpGet("status/default")]
    public ActionResult<string> GetDefaultStatus()
    {
        // Tests: using static — Scatter won't see "StatusType" at usage sites
        var status = Active;
        return Ok(status.ToString());
    }

    [HttpGet("person")]
    public ActionResult<PersonDto> GetSamplePerson()
    {
        // Tests: record type usage — PersonDto is a positional record
        // No per-file `using GalaxyWorks.Common.Models` — comes from GlobalUsings.cs
        var person = new PersonDto("Jane Doe", 30, "jane@galaxy.com");
        return Ok(person);
    }

    [HttpGet("employee")]
    public ActionResult<EmployeeDto> GetSampleEmployee()
    {
        // Tests: record inheritance
        var emp = new EmployeeDto("John Smith", 28, "john@galaxy.com", "Engineering");
        return Ok(emp);
    }

    [HttpGet("greeting/{name}")]
    public ActionResult<string> GetGreeting(string name)
    {
        // Tests: extension method usage — no reference to StringExtensions type
        // Comes from GlobalUsings.cs: `global using GalaxyWorks.Common.Extensions;`
        var greeting = $"Hello, {name.Truncate(20)}!";
        return Ok(greeting);
    }
}
