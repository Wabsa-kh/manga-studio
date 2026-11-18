# Daily worker setup

The source repository is public. Credentials and the manga/media archive remain private. Standard public GitHub-hosted Linux runners are free; Drive capacity, Google API quotas and Colab GPU access have their own limits. No paid fallback is enabled.

The scheduled worker runs at **08:17 UTC / 13:17 Pakistan every day**. GitHub may delay scheduled jobs. It resumes saved work and attempts at most one completed upload per run. A daily finished hour is a target, not a guaranteed entitlement.

## Files and secrets

Keep these files in a private folder OUTSIDE the repository. The setup helper installs their contents using GitHub CLI stdin, without displaying values. Never commit them.

| Private file | GitHub Actions secret | Purpose |
|---|---|---|
| gemini-key.txt | GEMINI_API_KEY | Existing Gemini key |
| rclone.conf | MANGA_RCLONE_CONFIG | Authorized gdrive remote |
| colab-adc.json | COLAB_ADC_JSON | Authorized user Colab credentials |
| youtube-token.json | YOUTUBE_TOKEN_JSON | YouTube offline OAuth credentials |
| youtube-channel-id.txt | YOUTUBE_CHANNEL_ID | Intended upload channel |

Repository variable `MANGA_STORE_REMOTE` is `gdrive:manga-studio`.

## 1. Drive

Install [rclone](https://rclone.org/downloads/). Run `rclone config`, create a new remote named `gdrive`, choose Google Drive, and authorize your account in the browser. Use a dedicated production folder if possible. Run `rclone mkdir gdrive:manga-studio`. `rclone config file` shows the configuration location; copy that file to the private setup folder as `rclone.conf`. Use an unencrypted rclone config for this secret (GitHub encrypts it at rest).

## 2. Colab

Install Google Cloud CLI. Use the account that has your Colab access:

```bash
gcloud auth application-default login --scopes=openid,https://www.googleapis.com/auth/cloud-platform,https://www.googleapis.com/auth/userinfo.email,https://www.googleapis.com/auth/colaboratory
```

Copy the resulting `application_default_credentials.json` into the private folder as `colab-adc.json`. On Windows it is normally under `%APPDATA%\gcloud`; on Linux under `~/.config/gcloud`. The worker runs the official Colab CLI on Linux. Actual free GPU availability must be checked with a real authorized run.

## 3. YouTube (private first)

1. In [Google Cloud Console](https://console.cloud.google.com/apis/library/youtube.googleapis.com), enable **YouTube Data API v3** in your project.
2. Configure the Google Auth Platform consent screen. For an external app in Testing, add your Google account as a test user.
3. Create an OAuth client of type **Desktop app**. Download the client JSON into the private folder as `google-client.json`. An API key alone cannot upload videos.
4. Install the project requirements, then run:

```bash
python scripts/setup_connections.py youtube --folder /your/private/setup-folder
python scripts/setup_connections.py install --folder /your/private/setup-folder
```

The first command opens Google consent, displays the chosen channel, and asks you to confirm it locally. It saves the two YouTube secret files. The install command sets all available real secrets and skips placeholders. Do not paste credential files into chat.

External apps left in Testing normally have refresh tokens that expire after seven days with these scopes. For unattended daily operation, configure the consent publishing status appropriately for your own app/account; any Google verification requirements still apply. Reauthorize locally if Google revokes or expires access. See [Google OAuth expiration](https://developers.google.com/identity/protocols/oauth2#expiration).

`config/settings.json` currently enables private uploads, one per run. Public publishing requires explicitly changing `youtube.privacy`. Upload receipts bind the file checksum, privacy and channel. Interrupted uploads probe the server and resume; expired or ambiguous sessions are held for review instead of automatically making a duplicate video. Video creation continues without YouTube credentials and queues completed parts. Ready uploads can run independently of missing generation credentials.

## 4. Start and resume

Open [Actions](https://github.com/Wabsa-kh/manga-studio/actions/workflows/production.yml), click **Run workflow**, leave dry-run enabled and verify connection booleans. Then run with dry-run off and a WeebCentral series URL. Later daily runs leave the URL empty and continue the private library automatically. Keep the workflow on `main`.

Edit model routes, local request ceilings, pacing, part duration, render options and upscale settings in `config/settings.json`. Limits are local ceilings, not guaranteed provider capacity; API quota responses persist cooldowns. Keys sharing a project do not multiply quota.

Detailed library reports, production errors, model usage receipts and completed media live in Drive checkpoints. Public Actions logs/artifacts contain only safe connection booleans and generic run status. Pull requests receive no production secrets. The production job is restricted to the canonical repository and main branch.

After fixing a connection, use the workflow `retry_manga_id` field for a blocked production job. Usage and quota history remain intact. YouTube holds are stored separately in each part's `youtube-upload.json`; inspect the real channel and receipt before resolving an ambiguous upload.

To retrieve a finished part and editable handoff locally (with your Drive environment connected):

```bash
python -m manga_bot.manage pull MANGA_ID part-001 --destination ./finished-part-001
```

Drive is the durable archive. Completed files are evicted from worker disk only after acknowledged checkpoints. No automatic destructive archive cleanup is enabled. A new worker hydrates assets when needed; model quota exhaustion preserves successful work.
