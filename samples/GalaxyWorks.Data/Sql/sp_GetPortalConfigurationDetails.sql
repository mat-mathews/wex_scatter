CREATE OR ALTER PROCEDURE dbo.sp_GetPortalConfigurationDetails
    @AdminIdentifier INT
AS
BEGIN
    SET NOCOUNT ON;

    SELECT
        ConfigId,
        PortalName,
        NotifyEnabled_fl = EnableNotifications,
        UserLimit = MaxUsers,
        ModifiedDate = LastUpdated,
        AdminKey = AdminApiKey
    FROM PortalConfigurations
    WHERE AdminId = @AdminIdentifier;
END
