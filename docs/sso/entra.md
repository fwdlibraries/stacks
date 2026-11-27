# Single sign-on with Microsoft Entra ID

Stacks signs people in with OpenID Connect, using the Authorization Code flow
with PKCE. These steps are for the IT team that manages your Entra tenant. They
take about 15 minutes. The library's Stacks administrator then enters the
values under **Administration → Sign-in**.

Students and instructors who open Stacks from the LMS are already signed in by
the LMS launch. Entra sign-in is for library staff, and for anyone else who uses
Stacks directly.

## What Stacks asks of Entra

- **Sign-in only.** Stacks requests the scopes `openid`, `email` and `profile`.
  It asks for no Microsoft Graph permissions and doesn't read mail, files or
  directory data.
- **Your tenant only.** Stacks uses your tenant's own issuer and checks the
  tenant ID (`tid`) in every token, so accounts from other Microsoft customers
  are refused.
- **Stable identity.** People are identified by tenant ID and object ID
  (`tid` + `oid`). Their email is used only to match an invitation the library
  sent.

## 1. Register the application

1. In the Entra admin center, go to **Identity → Applications → App
   registrations → New registration**.
2. Fill in the registration:
   - **Name:** `Stacks (reading lists)`
   - **Supported account types:** *Accounts in this organizational directory
     only* (single tenant).
   - **Redirect URI:** choose the **Web** platform and enter the address shown
     under Administration → Sign-in in Stacks. It looks like this:

     ```
     https://stacks.library.example.edu/api/v1/auth/oidc/callback
     ```

3. Select **Register**.

From the **Overview** page, note the **Application (client) ID** and the
**Directory (tenant) ID**.

## 2. Create a client secret

1. Go to **Certificates & secrets → Client secrets → New client secret**.
2. Choose an expiry; 12 or 24 months is typical. Record the expiry date
   somewhere, because sign-in stops working when the secret expires.
3. Copy the secret's **Value** (not its ID). It is shown only once.

Send the secret to the Stacks administrator through your usual secure channel,
not by plain email or chat. Stacks stores it encrypted and never displays it
again.

## 3. Token settings

Entra includes the needed claims by default. No optional claims are required.

If you want Stacks to enforce MFA itself (the **Require multi-factor
authentication** setting), Stacks checks the `amr` claim for `mfa`. A
Conditional Access policy that requires MFA for this app does the same job, and
we recommend it either way.

## 4. App roles (optional)

App roles let you manage Stacks roles in Entra instead of in Stacks.

1. Go to **App roles → Create app role** and create the roles you want, each
   with **Allowed member types:** *Users/Groups*:

   | Display name           | Value                  |
   |------------------------|------------------------|
   | Stacks Administrator   | `Stacks.Administrator` |
   | Stacks Librarian       | `Stacks.Librarian`     |
   | Stacks Viewer          | `Stacks.Viewer`        |

2. Go to **Enterprise applications → Stacks (reading lists) → Users and
   groups** and assign people or groups to the roles. Assigning groups requires
   Entra ID P1 or higher.
3. Optional: under **Enterprise applications → Properties**, set **Assignment
   required?** to *Yes* so that only assigned people can sign in.

In Stacks, the administrator maps each value to a Stacks role. Mapped roles
apply to the whole organization and follow Entra: they are added or removed
each time the person signs in. Roles granted inside Stacks, such as librarian
access to a single department, are never changed by this mapping.

## 5. Send these to the Stacks administrator

- **Issuer:** `https://login.microsoftonline.com/<Directory (tenant) ID>/v2.0`
  Use the tenant ID itself, not `common` or `organizations`; Stacks refuses
  those.
- **Client ID:** the Application (client) ID
- **Client secret:** sent separately, through a secure channel
- **Email domains** that may sign in, e.g. `example.edu`
- **App role values**, if you created any

## Google Workspace and OpenAthens

If Google Workspace or OpenAthens federates through Entra, people sign in
through Entra as usual. Stacks needs only the Entra registration above.

## Rotating the secret

Before the secret expires:

1. Create a new client secret in Entra.
2. Paste it into Administration → Sign-in and save.
3. After someone has signed in successfully, delete the old secret in Entra.
