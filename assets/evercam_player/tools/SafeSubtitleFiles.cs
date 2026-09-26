using System;
using System.IO;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

// Windows PowerShell 5.1 compatible. Directory handles deny delete sharing.
public sealed class SafeSubtitleFiles : IDisposable {
    readonly List<SafeFileHandle> pins = new List<SafeFileHandle>();
    readonly string root;
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    static extern SafeFileHandle CreateFile(string path, uint access, uint share,
        IntPtr security, uint creation, uint flags, IntPtr template);
    [DllImport("kernel32.dll", SetLastError=true)]
    static extern bool GetFileInformationByHandleEx(SafeFileHandle handle,
        int infoClass, out TagInfo info, uint size);
    [StructLayout(LayoutKind.Sequential)]
    struct TagInfo { public uint attributes; public uint tag; }
    static bool Windows { get { return Environment.OSVersion.Platform == PlatformID.Win32NT; } }
    static SafeFileHandle Open(string path, bool directory) {
        SafeFileHandle handle = CreateFile(path, 0x80000000, directory ? 3u : 1u,
            IntPtr.Zero, 3, 0x00200000u | (directory ? 0x02000000u : 0u), IntPtr.Zero);
        if (handle.IsInvalid) { handle.Dispose(); throw new IOException("Cannot safely open: " + path); }
        TagInfo info;
        if (!GetFileInformationByHandleEx(handle, 9, out info, 8) ||
            (info.attributes & 0x400) != 0 || ((info.attributes & 0x10) != 0) != directory) {
            handle.Dispose(); throw new IOException("Unsafe link or file type: " + path);
        }
        return handle;
    }
    public SafeSubtitleFiles(string folder) {
        root = Path.GetFullPath(folder);
        try {
            if (Windows) {
                var chain = new Stack<string>();
                for (var dir = new DirectoryInfo(root); dir != null; dir = dir.Parent) chain.Push(dir.FullName);
                while (chain.Count != 0) pins.Add(Open(chain.Pop(), true));
            } else {
                // The shipped updater targets Windows; refuse links on other platforms too.
                Check(root, true);
            }
        } catch { Dispose(); throw; }
    }
    static bool Check(string path, bool directory) {
        FileAttributes attr;
        try { attr = File.GetAttributes(path); }
        catch (FileNotFoundException) { return false; }
        if ((attr & FileAttributes.ReparsePoint) != 0 ||
            ((attr & FileAttributes.Directory) != 0) != directory)
            throw new IOException("Unsafe link or file type: " + path);
        return true;
    }
    string Child(string name) {
        if (String.IsNullOrEmpty(name) || name == "." || name == ".." || name.IndexOfAny(new char[]{'/', '\\', ':'}) >= 0)
            throw new IOException("Unsafe filename");
        return Path.Combine(root, name);
    }
    public string Read(string name) {
        string path = Child(name);
        Check(path, false);
        if (!Windows) return File.ReadAllText(path, Encoding.UTF8);
        using (var handle = Open(path, false))
        using (var stream = new FileStream(handle, FileAccess.Read))
        using (var reader = new StreamReader(stream, Encoding.UTF8, true)) return reader.ReadToEnd();
    }
    public void Write(string name, string text) {
        string output = Child(name);
        Check(output, false);
        string temporary = Child(".vts-" + Guid.NewGuid().ToString("N") + ".tmp");
        bool owned = false;
        try {
            using (var stream = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None)) {
                owned = true;
                byte[] bytes = new UTF8Encoding(false).GetBytes(text);
                stream.Write(bytes, 0, bytes.Length);
                stream.Flush(true);
            }
            if (Check(output, false)) File.Replace(temporary, output, null);
            else File.Move(temporary, output);
        } finally { if (owned) File.Delete(temporary); }
    }
    public void Dispose() {
        for (int i = pins.Count - 1; i >= 0; --i) pins[i].Dispose();
        pins.Clear();
    }
}
