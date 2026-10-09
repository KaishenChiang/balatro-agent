// MIT. A small Windows GUI entry point; preparation stays in the project scripts.
using System;
using System.Diagnostics;
using System.IO;
using System.Globalization;
using System.Reflection;
using System.Text;
using System.Windows.Forms;

[assembly: AssemblyTitle("Balatro Agent")]
[assembly: AssemblyDescription("Local AI game preparation")]
[assembly: AssemblyCompany("Balatro Agent contributors")]
[assembly: AssemblyProduct("Balatro Agent")]
[assembly: AssemblyCopyright("MIT, 2026 Balatro Agent contributors")]
[assembly: AssemblyVersion("1.2.0.0")]
[assembly: AssemblyFileVersion("1.2.0.0")]

internal static class Launcher
{
    // ProcessStartInfo uses Windows argv quoting, never cmd.exe or shell code.
    private static string Quote(string value)
    {
        var result = new StringBuilder("\"");
        int slashes = 0;
        foreach (char character in value)
        {
            if (character == '\\') { slashes++; continue; }
            if (character == '"') { result.Append('\\', slashes * 2 + 1); result.Append('"'); }
            else { result.Append('\\', slashes); result.Append(character); }
            slashes = 0;
        }
        result.Append('\\', slashes * 2);
        return result.Append('"').ToString();
    }

    [STAThread]
    private static int Main(string[] args)
    {
        bool english = CultureInfo.CurrentUICulture.TwoLetterISOLanguageName != "zh";
        try
        {
            // Resolve the explicit language before errors such as an incomplete ZIP.
            for (int i = 0; i < args.Length; i++)
            {
                if (args[i] == "--language" && i + 1 < args.Length)
                {
                    string value = args[++i];
                    if (value == "en") english = true;
                    else if (value == "zh-CN") english = false;
                    else if (value != "auto") throw new ArgumentException(english ? "Language must be auto, en or zh-CN." : "语言参数须为 auto、en 或 zh-CN。");
                }
            }
            string root = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
            string script = Path.Combine(root, "scripts", "launcher.ps1");
            if (!File.Exists(script)) throw new FileNotFoundException(english ? "Extract the complete project folder, then open Balatro Agent.exe." : "请解压完整的项目目录，再打开 Balatro Agent.exe。");
            string arguments = "-NoProfile -NonInteractive -STA -ExecutionPolicy Bypass -File " + Quote(script);
            bool hasPreviewOptions = false;
            // Preview is for offline UI checks. It cannot start preparation.
            for (int i = 0; i < args.Length; i++)
            {
                if (args[i] == "--preview") arguments += " -Preview";
                else if ((args[i] == "--preview-state" || args[i] == "--preview-image") && i + 1 < args.Length)
                {
                    hasPreviewOptions = true;
                    string option = args[i] == "--preview-state" ? " -PreviewState " : " -PreviewImage ";
                    arguments += option + Quote(args[++i]);
                }
                else if (args[i] == "--language" && i + 1 < args.Length)
                    arguments += " -Language " + Quote(args[++i]);
                else throw new ArgumentException(english ? "Unsupported launcher argument." : "不支持的启动参数。");
            }
            if (hasPreviewOptions && Array.IndexOf(args, "--preview") < 0)
                throw new ArgumentException(english ? "Preview options require --preview." : "预览参数需要 --preview。");
            var start = new ProcessStartInfo {
                FileName = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "WindowsPowerShell", "v1.0", "powershell.exe"),
                Arguments = arguments, WorkingDirectory = root,
                UseShellExecute = false, CreateNoWindow = true,
                WindowStyle = ProcessWindowStyle.Hidden
            };
            using (var process = Process.Start(start))
            {
                if (process == null) throw new InvalidOperationException(english ? "Could not open the preparation window." : "无法启动准备窗口。");
                process.WaitForExit();
                return process.ExitCode;
            }
        }
        catch (Exception error)
        {
            MessageBox.Show(error.Message, "Balatro Agent", MessageBoxButtons.OK, MessageBoxIcon.Information);
            return 1;
        }
    }
}
