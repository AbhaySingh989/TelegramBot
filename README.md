# 💻 Multimodal AI Agent

This repository contains a sophisticated, multi-modal AI agent built as a Telegram bot. The agent leverages the power of Google's Gemini Pro to offer a rich, interactive experience, including conversational AI, personal journaling with deep analysis, and optical character recognition (OCR).

## 👤 Author

**Abhay Singh**
- 📧 Email: [abhay.rkvv@gmail.com]
- 🐙 GitHub: [AbhaySingh989]
- 💼 LinkedIn: [[Abhay Singh](https://www.linkedin.com/in/abhay-pratap-singh-905510149/)]

## Key Features

- **Multi-Modal Interaction**: Communicate with the bot using text, voice, or images. The bot intelligently processes each input type to provide the appropriate response.
- **Three Core Modes**:
    - **🤖 Chatbot Mode**: Engage in open-ended conversations with a powerful AI.
    - **📓 Journal Mode**: A private and secure space to record your thoughts.
        - **AI-Powered Analysis**: Receive insights into your journal entries, including sentiment, key topics, and thematic categories.
        - **Mind Map Visualization**: Get a `graphviz`-generated mind map that visually represents the core themes of your entry.
        - **Daily Prompts**: Opt-in to receive daily prompts to inspire your journaling practice.
    - **📄 OCR Mode**: Extract text from any image with high accuracy.
- **User-Friendly Interface**:
    - **Display Name**: Personalize your experience by setting a custom display name.
    - **Command-Based Navigation**: Easily switch between modes and access features with simple commands.
- **Token Tracking**: Monitor your Gemini API token usage with a dedicated command.
- **Persistent Storage**: All user data, journal entries, and feedback are securely stored in a local SQLite database.

## How It Works

The bot is built with Python and leverages several key libraries:

- **`python-telegram-bot`**: For all interactions with the Telegram API.
- **`google-generativeai`**: To integrate with the Gemini Pro model for all AI-powered features.
- **`SQLite`**: For data storage.
- **`Graphviz`**: To generate mind map visualizations of journal entries.
- **`Pillow`**: For image processing.

The bot's architecture is centered around a `ConversationHandler` that manages the user's state (i.e., which mode they are in). When a user sends a message, the bot processes the input, routes it to the appropriate mode's logic, and generates a response.

## Installation

1.  **Clone the repository**:
    ```bash
    git clone https://github.com/your-username/your-repo-name.git
    cd your-repo-name
    ```
2.  **Install dependencies**:
    ```bash
    pip install -r requirements.txt
    ```
    You will also need to install Graphviz. You can find installation instructions for your operating system here: [https://graphviz.org/download/](https://graphviz.org/download/)

3.  **Set up your environment variables**:
    - Create a file named `.env` in the root of the project.
    - Add your Telegram Bot Token and Gemini API Key to the `.env` file like this:
        ```
        TELEGRAM_BOT_TOKEN="YOUR_TELEGRAM_BOT_TOKEN"
        GEMINI_API_KEY="YOUR_GEMINI_API_KEY"
        ```

## Usage

1.  **Run the bot**:
    ```bash
    python New_Main.py
    ```
2.  **Interact with the bot on Telegram**:
    - Open Telegram and search for your bot.
    - Send the `/start` command to begin.
    - Use the inline buttons to select a mode.
    - Start chatting, journaling, or sending images for OCR!

## Commands

- `/start`, `/mode`, `/changemode`: Start the bot and select a mode.
- `/setusername <name>`: Set your display name.
- `/tokens`: Check your Gemini API token usage.
- `/feedback <message>`: Send feedback to the developers.
- `/enableprompts`: Enable daily journal prompts.
- `/disableprompts`: Disable daily journal prompts.
- `/end`: End the current session.
- `/cancel`: Cancel the current action and return to mode selection.
- `/help`: Show the help message.

## 🤝 Contributing

I welcome contributions! Here's how you can help:

1. **🍴 Fork** the repository
2. **🌿 Create** a feature branch (`git checkout -b feature/amazing-feature`)
3. **💾 Commit** your changes (`git commit -m 'Add amazing feature'`)
4. **📤 Push** to the branch (`git push origin feature/amazing-feature`)
5. **🔄 Open** a Pull Request


## 🙏 Acknowledgments

- 🤖 **Google AI** for providing the powerful Gemini 2.0 Flash model
- 🔗 **LangChain** for the excellent multimodal processing framework
- 📱 **python-telegram-bot** for the robust Telegram bot API wrapper
- 🌟 **Open Source Community** for continuous inspiration and support


## 📜 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
```
MIT License

Copyright (c) 2025 Abhay Singh

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
