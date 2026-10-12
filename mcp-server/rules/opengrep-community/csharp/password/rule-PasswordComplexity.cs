// License: LGPL-3.0 License (c) security-code-scan
using dotNetMVC.Data;
using Microsoft.AspNetCore.Identity;
using Microsoft.AspNetCore.Identity.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;

var builder = WebApplication.CreateBuilder(args);

builder.Services.AddIdentity<IdentityUser, IdentityRole>(options =>
{
    // ok: csharp_password_rule-PasswordComplexity
    options.Password.RequireDigit = true;
    // ok: csharp_password_rule-PasswordComplexity
    options.Password.RequireLowercase = true;
    // ok: csharp_password_rule-PasswordComplexity
    options.Password.RequireNonAlphanumeric = true;
    // ok: csharp_password_rule-PasswordComplexity
    options.Password.RequireUppercase = true;
})
 .AddEntityFrameworkStores<AppDbContext>()
 .AddDefaultTokenProviders();

builder.Services.Configure<IdentityOptions>(options =>
{
    // ruleid: csharp_password_rule-PasswordComplexity
    options.Password.RequiredLength = 5;
    // ok: csharp_password_rule-PasswordComplexity
    options.Password.RequiredUniqueChars = 1;
});


namespace BTCPayServer.Hosting
{
    public class Startup
    {
        public void ConfigureServices(IServiceCollection services)
        {
            services.AddIdentityCore<UserInfo>(options =>
            {
                // ok: csharp_password_rule-PasswordComplexity
                options.Password.RequireUppercase = true;
                // ruleid: csharp_password_rule-PasswordComplexity
                options.Password.RequireNonAlphanumeric = false;
            }).AddEntityFrameworkStores<AppDbContext>()
            .AddDefaultTokenProviders();

            services.Configure<IdentityOptions>(options =>
            {
                // ok: csharp_password_rule-PasswordComplexity
                options.Password.RequireDigit = true;
                // ruleid: csharp_password_rule-PasswordComplexity
                options.Password.RequiredLength = 6;
                // ruleid: csharp_password_rule-PasswordComplexity
                options.Password.RequireLowercase = false;
                // ruleid: csharp_password_rule-PasswordComplexity
                options.Password.RequireNonAlphanumeric = false;
                // ruleid: csharp_password_rule-PasswordComplexity
                options.Password.RequireUppercase = false;
                // ruleid: csharp_password_rule-PasswordComplexity
                options.Password.RequireUppercase = false;
            });
        }
    }
}
