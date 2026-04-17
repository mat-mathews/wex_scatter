# Source Project → Pipeline Cascade Simulation (P-intersect)

**Source stems supplied:** 1640
**Resolved (any level):** 43 (2.6%)
**Unresolved:** 1597 (97.4%)

- L1 exact: 33 (2.0%)
- L2 Jaccard ≥0.7: 4 (0.2%)
- L3 tail-2 tokens: 6 (0.4%)

## L1 (33) — ambiguous: 16
- `BankingService.WindowsServiceHost` → `cdh-bankingservice-az-cd`
- `LH1OnDemand.DebitCardService.FinancialServiceHost` → `cdh-debitcard-financial-az-cd`
- `Lighthouse1.Exports.Scheduler` ⚠ → `cdh-exportscheduler-nav1-az-cd`, `cdh-exportscheduler-nav10-az-cd`, `cdh-exportscheduler-nav11-az-cd`, `cdh-exportscheduler-nav12-az-cd`, `cdh-exportscheduler-nav13-az-cd`, `cdh-exportscheduler-nav14-az-cd`, `cdh-exportscheduler-nav15-az-cd`, `cdh-exportscheduler-nav16-az-cd`, `cdh-exportscheduler-nav17-az-cd`, `cdh-exportscheduler-nav18-az-cd`, `cdh-exportscheduler-nav19-az-cd`, `cdh-exportscheduler-nav20-az-cd`, `cdh-exportscheduler-nav21-az-cd`, `cdh-exportscheduler-nav22-az-cd`, `cdh-exportscheduler-nav23-az-cd`, `cdh-exportscheduler-nav24-az-cd`, `cdh-exportscheduler-nav25-az-cd`, `cdh-exportscheduler-nav4-az-cd`, `cdh-exportscheduler-nav5-az-cd`, `cdh-exportscheduler-nav6-az-cd`, `cdh-exportscheduler-nav7-az-cd`, `cdh-exportscheduler-nav8-az-cd`, `cdh-exportscheduler-nav9-az-cd`
- `LH1.FileImport.FileLoaderService` ⚠ → `cdh-cdex-fileloader-nav1-az-cd`, `cdh-cdex-fileloader-nav10-az-cd`, `cdh-cdex-fileloader-nav11-az-cd`, `cdh-cdex-fileloader-nav13-az-cd`, `cdh-cdex-fileloader-nav14-az-cd`, `cdh-cdex-fileloader-nav21-az-cd`, `cdh-cdex-fileloader-nav23-az-cd`, `cdh-cdex-fileloader-nav24-az-cd`, `cdh-cdex-fileloader-nav25-az-cd`, `cdh-cdex-fileloader-nav5-az-cd`, `cdh-cdex-fileloader-nav6-az-cd`, `cdh-cdex-fileloader-nav7-az-cd`, `cdh-cdex-fileloader-nav9-az-cd`, `cdh-cdex-fileloader-navgen-az-cd`
- `LH1.FileImport.ImportManagerService` ⚠ → `cdh-cdex-importmanager-az-cd`, `cdh-cdex-importmanager-cd`
- `Lh1.FileProcessor.Service` ⚠ → `cdh-fileprocessor-az-cd`, `cdh-fileprocessor-card-az-cd`
- `SchwabIntegrator.Service` → `cdh-schwabintegrator-az-cd`
- `LH1OnDemand.WebService.DMZServices` → `cdh-dmzservices-az-cd`
- `Lighthouse1.NTServices.ClaimsImport.ProcessingService` ⚠ → `cdh-claimsimport-processing-az-cd`, `cdh-claimsimport-processing-cd`
- `Lighthouse1.NTServices.ClaimsImport.ValidationService` ⚠ → `cdh-claimsimport-validation-az-cd`, `cdh-claimsimport-validation-cd`
- `LH1AdministratorSetup` → `cdh-tpasetup-az-cd`
- `SSOLoginTestApp` → `cdh-ssotest-az-cd`
- `Lighthouse1.FileImport.FileWatcher` ⚠ → `cdh-cpf-az-cd`, `cdh-cpf-hsabank-az-cd`
- `DebitCardIntegration` ⚠ → `cdh-taskhost-debitcard1-az-cd`, `cdh-taskhost-debitcard2-az-cd`, `cdh-taskhost-debitcard3-az-cd`
- `Lighthouse1.Apps.Console.AccountingProcessor` → `cdh-batchprocesses-cd`
- `WEXHealth.CDH.Configuration.Indexer` → `cdh-configuration-indexer-az-cd`
- `Lighthouse1.Apps.Service.QueueListenerService` → `cdh-queuelistener-az-cd`
- `Lighthouse1.Apps.Service.TaskHost` ⚠ → `cdh-taskhost-az-cd`, `cdh-taskhost-bankrpt01-az-cd`, `cdh-taskhost-bankrpt01-cd`, `cdh-taskhost-baphv-az-cd`, `cdh-taskhost-comm01-az-cd`, `cdh-taskhost-debitcard1-az-cd`, `cdh-taskhost-debitcard2-az-cd`, `cdh-taskhost-debitcard3-az-cd`, `cdh-taskhost-debitcardevent-az-cd`, `cdh-taskhost-hsa01-az-cd`, `cdh-taskhost-wf01-az-cd`, `cdh-taskhost-wf02-az-cd`, `cdh-taskhost-wf03-az-cd`, `cdh-taskhost-wf04-az-cd`
- `Lighthouse1.Apps.Web.AutoPayBalanceInquiry` → `cdh-balancequery-az-cd`
- `Lighthouse1.Apps.Web.ExchangeIntegrationService` ⚠ → `cdh-cws-az-cd`, `cdh-cws-cd`, `cdh-cws-internal-az-cd`
- `Lighthouse1.Apps.Web.SecurityIdentityService` ⚠ → `cdh-sis-az-cd`, `cdh-sis-cd`
- `WexHealth.Apps.Web.Employer.Auth.Service` ⚠ → `cdh-authservice-az-cd`, `cdh-authservice-cd`
- `WexHealth.Apps.Employer.Auth.TaskService` → `cdh-employerauth-taskservice-az-cd`
- `WexHealth.CDH.NewEmployerSetup.Portal` → `cdh-newemployersetup-az-cd`
- `WexHealth.Apps.Web.Employer.Portal` → `cdh-employerportal-az-cd`
- `WexHealth.CDH.Apps.Web.EmployerUser.Api` ⚠ → `cdh-employeruser-az-cd`, `cdh-employeruser-cd`
- `WexHealth.Apps.Web.HealthPlanning.Portal` ⚠ → `cdh-healthplanning-az-cd`, `cdh-healthplanning-cd`
- `WEXHealth.CDH.SSO.ServiceProvider` → `cdh-sso-serviceprovider-az-cd`
- `WexHealth.CDH.App.FileImportTestHarness` → `cdh-fileimport-tool-az-cd`
- `WexHealth.CDH.Investment.WebApi` ⚠ → `cdh-investment-api`, `cdh-investment-api-az-cd`
- `UploadCDExTemplateExternal` → `UploadCDExTemplateExternalTool`
- `WexHealth.Services.ExternalDocuments` → `cdh-employer-extdocs-az-cd`
- `Lighthouse1.Services.Employer` ⚠ → `cdh-employerservices-internal-az-cd`, `cdh-employerservices-v30-az-cd`, `cdh-employerservices-v31-az-cd`

## L2 (4) — ambiguous: 3
- `WexHealth.Apps.Web.EmployerPortal.Settings` → `cdh-employerportal-az-cd`
- `WexHealth.Apps.Web.Data.Api` ⚠ → `cdh-dataapi-az-cd`, `cdh-dataapi-cd`
- `WexHealth.Apps.Web.HealthPlanning.Portal.Tests` ⚠ → `cdh-healthplanning-az-cd`, `cdh-healthplanning-cd`
- `Lighthouse1.Nbc.WebService.NbcWebApi.UnitTests` ⚠ → `cdh-nbcapi-az-cd`, `cdh-nbcapi-az-cicd`

## L3 (6) — ambiguous: 6
- `LH1.Test.FileImport.FileWatcher` ⚠ → `cdh-cpf-az-cd`, `cdh-cpf-hsabank-az-cd`
- `Evolution1.Authorization.Services` ⚠ → `cdh-mobile-authorization-mws-az-cd`, `cdh-mobile-authorization-mws-cd`, `cdh-mobile-authorization-services-az-cd`, `cdh-mobile-authorization-services-cd`, `cdh-mobile-canary-authorization-mws-az-cd`
- `Evolution1.Consumer.MobileProductInstanceService` ⚠ → `cdh-mobile-canary-mpi-mws-az-cd`, `cdh-mobile-mpi-mws-az-cd`, `cdh-mobile-mpi-mws-cd`, `cdh-mobile-mpi-services-az-cd`, `cdh-mobile-mpi-services-cd`
- `Evolution1.IdentityProvider.Services` ⚠ → `cdh-mobile-canary-idpsvc-mws-az-cd`, `cdh-mobile-idpsvc-mws-az-cd`, `cdh-mobile-idpsvc-mws-cd`, `cdh-mobile-idpsvc-services-az-cd`, `cdh-mobile-idpsvc-services-cd`
- `Evolution1.IdentityProvider.Web` ⚠ → `cdh-mobile-identityweb-az-cd`, `cdh-mobile-identityweb-cd`
- `LH1.Test.FileImport.FileWatcher` ⚠ → `cdh-cpf-az-cd`, `cdh-cpf-hsabank-az-cd`

## NONE (1597) — ambiguous: 0
- `WEX.Benefits.BenefitsWebhooks.Application` → (no candidates)
- `WEX.Benefits.BenefitsWebhooks.Domain` → (no candidates)
- `WEX.Benefits.BenefitsWebhooks.Infrastructure` → (no candidates)
- `WEX.Benefits.BenefitsWebhooks.Persistence` → (no candidates)
- `WEX.Benefits.BenefitsWebhooks.Api` → (no candidates)
- `WEX.Benefits.BenefitsWebhooks.Api.IntegrationTests` → (no candidates)
- `WEX.Benefits.BenefitsWebhooks.Api.UnitTests` → (no candidates)
- `WEX.Benefits.BenefitsWebhooks.Application.UnitTests` → (no candidates)
- `WEX.Benefits.BenefitsWebhooks.Domain.UnitTests` → (no candidates)
- `WEX.Benefits.BenefitsWebhooks.Infrastructure.UnitTests` → (no candidates)
- `WEX.Benefits.BenefitsWebhooks.Persistence.UnitTests` → (no candidates)
- `ConfigurationSample` → (no candidates)
- `IdentityServerIdp` → (no candidates)
- `TestClient` → (no candidates)
- `WEXHealth.Enterprise.Operations.Web` → (no candidates)
- `TaskHost.CommonTestPlatform` → (no candidates)
- `TaskHost.Core.TestingMocks` → (no candidates)
- `TaskHost.Core.UnitTests` → (no candidates)
- `TaskHost.Macro.Autofac.UnitTests` → (no candidates)
- `TaskHost.Macro.UnitTests` → (no candidates)
- `TaskHost.Metrics.UnitTests` → (no candidates)
- `TaskHost.TestingMocks` → (no candidates)
- `TaskHost.Threading.UnitTests` → (no candidates)
- `WEXHealth.Enterprise.TaskHost` → (no candidates)
- `WEXHealth.Enterprise.TaskHost.ConsoleUtilityFramework` → (no candidates)
- `WEXHealth.Enterprise.TaskHost.Core` → (no candidates)
- `WEXHealth.Enterprise.TaskHost.TaskExecutionStrategies` → (no candidates)
- `WEXHealth.Enterprise.TaskHost.ExtensionMethods` → (no candidates)
- `WEXHealth.Enterprise.TaskHost.Logging` → (no candidates)
- `WEXHealth.Enterprise.TaskHost.Macro` → (no candidates)
- `WEXHealth.Enterprise.TaskHost.Macro.Autofac` → (no candidates)
- `WEXHealth.Enterprise.TaskHost.Metadata` → (no candidates)
- `WEXHealth.Enterprise.TaskHost.Metrics` → (no candidates)
- `WEXHealth.Enterprise.TaskHost.Pipeline` → (no candidates)
- `WEXHealth.Enterprise.TaskHost.StatusMonitoring.Framework` → (no candidates)
- `WEXHealth.Enterprise.TaskHost.StatusMonitoring.Framework.Autofac` → (no candidates)
- `WEXHealth.Enterprise.TaskHost.StatusMonitoring.Plugins` → (no candidates)
- `WEXHealth.Enterprise.TaskHost.Threading` → (no candidates)
- `WEXHealth.CDH.AdminPortal.PostDeployTests` → (no candidates)
- `WEXHealth.CDH.ConsumerPortal.PostDeployTests` → (no candidates)
- `Helpers` → (no candidates)
- `1PlanStoredProcedures` → (no candidates)
- `Automations` → (no candidates)
- `ConsoleApp` → (no candidates)
- `Test Project` → (no candidates)
- `eQA Demo` → (no candidates)
- `Mobile` → (no candidates)
- `TestProject1` → (no candidates)
- `Vineela` → (no candidates)
- `GreenplumRunConcurrentQueries` → (no candidates)
(… 1547 more)
