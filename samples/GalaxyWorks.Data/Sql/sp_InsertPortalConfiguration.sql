CREATE PROCEDURE [dbo].[sp_InsertPortalConfiguration]
    @PortalName_val NVARCHAR(100),
    @EnableNotifications_fl BIT,
    @MaxUsers_qty INT,
    @AdminApiKey_guid UNIQUEIDENTIFIER,
    @ConfigId_out INT OUTPUT
AS
BEGIN
    SET NOCOUNT ON;

    INSERT INTO PortalConfigurations (PortalName, EnableNotifications, MaxUsers, AdminApiKey, CreatedDate)
    VALUES (@PortalName_val, @EnableNotifications_fl, @MaxUsers_qty, @AdminApiKey_guid, GETUTCDATE());

    SET @ConfigId_out = SCOPE_IDENTITY();
END
