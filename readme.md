# Lorecard

Create characters and lorebooks from URLs using LLMs.

## Screenshots & Videos

<details>
  <summary>Lorebook Workflow</summary>
  
  *A video demonstrating the main workflow of creating a lorebook from a URL*

https://github.com/user-attachments/assets/d34efdb7-a5ec-4c9c-ab2b-b633fa59b3ca

</details>

<details>
  <summary>Character Workflow</summary>
  
  *A video demonstrating the main workflow of creating a character from a URL*

https://github.com/user-attachments/assets/abd86ee8-b347-40f2-a768-cb83d5607d1f

</details>

<details>
  <summary>[Lorebook]Manage Sources</summary>
  
  ![Lorebook Manage Sources](showcase/lorebook-manage-sources.png)

  ![Lorebook Edit Sources](showcase/lorebook-edit-source.png)
  
</details>

<details>
  <summary>[Lorebook]Confirming Links</summary>
  
  ![Lorebook Confirming Links](showcase/lorebook-confirm-links.png)
  
</details>

<details>
  <summary>[Lorebook]Generate Entries</summary>
  
  ![Lorebook Generate Entries](showcase/lorebook-generate-entries.png)
  
</details>

<details>
  <summary>[Lorebook]Completed Lorebook</summary>
  
  *The final generated lorebook, structured and ready for use.*
  
  ![Completed Lorebook](showcase/lorebook-complete.png)
</details>

<details>
  <summary>[Character]Overview</summary>
  
  ![Character Overview](showcase/character-complete.png)
  
</details>

<details>
  <summary>[Character]Regenerate</summary>
  
  ![Character Regenerate](showcase/character-regenerate.png)
  
</details>

<details>
  <summary>Project Analytics</summary>
  
  ![Project Analytics](showcase/project-analytics.png)
  
</details>

<details>
  <summary>API Request Logs</summary>
  
  ![API Request Logs](showcase/api-request-logs.png)
  
</details>

## Some notes
- **Lorebook creation:** This is not deep research; it doesn't involve a web search. You need to give a URL that has multiple links. _Fandom:category_ pages are perfect for the app. For example, you can give [Oblivion Skill Books](https://elderscrolls.fandom.com/wiki/Category:Oblivion:_Skill_Books). So this is going to extract all books and navigate one by one, and create a lorebook for each book.
- **Character creation:** You can simply give a URL for a character. It will extract the the page.
- You can see all API request logs on the API Requests modal. You can also see the project analytics on the Project Analytics modal.
- You can edit all prompts on the _Global Templates_ page and _Project Edit_ modal.

### Local OpenAI-compatible LLMs
For local servers such as KoboldCpp, oobabooga/text-generation-webui, LM Studio, or Ollama, create an **Openai_compatible** credential and set the base URL to the server's OpenAI-compatible API root, not the chat completions endpoint. Examples:

- `http://127.0.0.1:5001/v1`
- `http://127.0.0.1:1234/v1`
- `http://127.0.0.1:11434/v1`

If Lorecard is running inside Docker and the LLM server is running on your host machine, use `host.docker.internal` instead of `127.0.0.1`, for example `http://host.docker.internal:5001/v1`.

OpenAI-compatible credentials do not auto-list models, so seeing `0 models` is expected. Enter the model name manually in the project model field and in the credential test field.

### Input token usage
#### Lorebook
1. **Search Params:** Single LLM request. This is a very simple operation. Input token is very low.
2. **Manage Sources & Crawl** _Discover & Scan_ button makes one LLM request per source. If `Max Crawl Depth` is more than 1, it will discover sub-categories and make an LLM request for each one. We give the LLM [cleaned html](https://github.com/bmen25124/lorecard/blob/main/server/src/services/scraper.py#L8), so token usage can be high. You can use _Rescan Selected_ to find new links on previously scanned sources without using the LLM.
3. **Generate Entries:** Request count = link count. We are giving the LLM [cleaned html -> markdown](https://github.com/bmen25124/lorecard/blob/main/server/src/services/scraper.py#L111). Token usage depends on the page length. This step typically consumes the most tokens.

#### Character
- It is only generate and regenate actions. However there are estimated token count for each source.

## How to Install and Run the Application

Choose the option that best fits your needs.

### Option 1: Quick Start with Docker (Recommended for Users)

**1. Create a directory and `.env` file**
First, create a folder on your computer for the application's data. Inside that folder, create a file named `.env` and add a secret key phrase.

```env
# .env file

# A secret key phrase for encrypting credentials. Can be any string, like a strong password.
# THIS KEY IS CRITICAL. IF YOU LOSE IT, ALL STORED CREDENTIALS WILL BE UNUSABLE.
APP_SECRET_KEY=yoursecretphrasehere

# The port the application will run on.
PORT=3000

# (Optional) For first-time setup, the app can create default credentials from these.
OPENROUTER_API_KEY=
GOOGLE_GEMINI_KEY=
OPENAI_COMPATIBLE_BASE_URL=
OPENAI_COMPATIBLE_API_KEY=
```

**2. Run the application**
Open your terminal in that same folder and choose one of the commands below.

*   **To run with SQLite (Simple & Recommended):**
    A `data` folder will be created in your current directory to store the database.

    *   **For Linux, macOS, or WSL:**
        ```bash
        docker run -d --name lorebook-app --restart unless-stopped -p 3000:3000 \
          --env-file .env \
          -e APP_ENV=production \
          -e DATABASE_TYPE=sqlite \
          -e DATABASE_URL=/app/server/data/lorecard.db \
          -v "$(pwd)/data:/app/server/data" \
          ghcr.io/bmen25124/lorecard:v2.6
        ```

    *   **For Windows (Command Prompt):**
        ```cmd
        docker run -d --name lorebook-app --restart unless-stopped -p 3000:3000 ^
          --env-file .env ^
          -e APP_ENV=production ^
          -e DATABASE_TYPE=sqlite ^
          -e DATABASE_URL=/app/server/data/lorecard.db ^
          -v "%cd%/data:/app/server/data" ^
          ghcr.io/bmen25124/lorecard:v2.6
        ```
        
    *   **For Windows (PowerShell):**
        ```powershell
        docker run -d --name lorebook-app --restart unless-stopped -p 3000:3000 `
          --env-file .env `
          -e APP_ENV=production `
          -e DATABASE_TYPE=sqlite `
          -e DATABASE_URL=/app/server/data/lorecard.db `
          -v "${pwd}/data:/app/server/data" `
          ghcr.io/bmen25124/lorecard:v2.6
        ```

*   **To run with PostgreSQL (Advanced):**
    This requires starting a separate database container first. These commands work on all platforms.

    ```bash
    # 1. Create a network
    docker network create lorebook-net

    # 2. Start the database container
    docker run -d --name lorebook-db --restart unless-stopped --network lorebook-net \
      -e POSTGRES_USER=user -e POSTGRES_PASSWORD=password -e POSTGRES_DB=lorecard \
      -v lorecard_postgres_data:/var/lib/postgresql/data \
      postgres:13

    # 3. Start the application container
    docker run -d --name lorebook-app --restart unless-stopped --network lorebook-net -p 3000:3000 \
      --env-file .env \
      -e APP_ENV=production \
      -e DATABASE_TYPE=postgres \
      -e DATABASE_URL=postgresql://user:password@lorebook-db:5432/lorecard \
      ghcr.io/bmen25124/lorecard:v2.6
    ```

---

### Option 2: Run from Source on Windows (`start.bat`)

Use this method if you are on Windows and prefer not to use Docker. This script automates the entire setup process.

**Prerequisites:**
You must have the following software installed and available in your PATH:
-   [Git](https://git-scm.com/downloads)
-   [Python](https://www.python.org/downloads/) (version 3.10 or higher)
-   [Node.js](https://nodejs.org/) (version 18 or higher)
-   [uv](https://github.com/astral-sh/uv) (run `pip install uv`)
-   [pnpm](https://pnpm.io/installation) (run `npm install -g pnpm`)

**1. Clone the repository**
```bash
git clone https://github.com/bmen25124/lorecard.git
cd lorecard
```

**2. Run the script**
Simply double-click the `start.bat` file or run it from your terminal:
```bash
.\start.bat
```
The first time you run it, the script will guide you through setting up your configuration (`.env` file), installing all dependencies, build the client, and start the server.

---

### Option 3: Run from Source with Docker Compose (For Developers)

Use this method if you have cloned the source code and want to build and run the application in a containerized environment. This is ideal for development.

**1. Clone the repository**
```bash
git clone https://github.com/bmen25124/lorecard.git
cd lorecard
```

**2. Configure your API Key**
Copy the example environment file.
```bash
# On Linux, macOS, or WSL
cp .env.example .env

# On Windows
copy .env.example .env
```
Now, open the new `.env` file and add your API keys. Don't forget to add `APP_SECRET_KEY` as well.

**3. Build and run the application**

*   **To run with SQLite (Default):**
    ```bash
    docker-compose up --build
    ```

*   **To run with PostgreSQL (Optional):**
    ```bash
    docker-compose -f docker-compose.yml -f docker-compose.postgres.yml up --build
    ```

---

### Accessing the App

Once running, the application will be available at:
**[http://127.0.0.1:3000/](http://127.0.0.1:3000/)**

To access it from another device on the same network, open `http://<computer-lan-ip>:3000/` on that device and make sure your firewall allows inbound traffic on port `3000`.

For access outside your home network, use a private network tool such as Tailscale, or deploy Lorecard on a VPS behind a reverse proxy such as nginx. Avoid exposing the app directly to the public internet without your own access controls.
