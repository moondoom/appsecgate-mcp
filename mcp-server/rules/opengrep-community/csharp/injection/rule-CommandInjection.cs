// License: LGPL-3.0 License (c) security-code-scan
using System.Diagnostics;

class CommandInjection
{
	static void ProcessWithStartInfoDirectUs1()
    {
        var p = new Process();
        // ok: csharp_injection_rule-CommandInjection
        p.StartInfo.FileName = "exportLegacy.exe";
        // ruleid: csharp_injection_rule-CommandInjection
        p.StartInfo.Arguments = " -user " + Console.ReadLine() + " -role user";
        p.Start();
    }

    static void ProcessWithStartInfoDirectUs2()
    {
        var p = new Process();
        // @"C:\Program Files\Internet Explorer\iexplore.exe"
        // ruleid: csharp_injection_rule-CommandInjection
        p.StartInfo.FileName = Console.ReadLine();
        // ok: csharp_injection_rule-CommandInjection
        p.StartInfo.Arguments =  "www.example.com";
        p.Start();
    }

	static void ProcessWithStartInfoDirectUs3()
	{
    	// @"C:\Program Files\Internet Explorer\iexplore.exe"
    	string arguments = Console.ReadLine();
    	var p = new Process();
    	// ok: csharp_injection_rule-CommandInjection
    	p.StartInfo.FileName = @"C:\Program Files\Internet Explorer\iexplore.exe";
    	// ruleid: csharp_injection_rule-CommandInjection
    	p.StartInfo.Arguments = arguments;
        p.Start();
	}

    static void ProcessWithStartInfoDirectS1()
    {
        var p = new Process();
        // @"C:\Program Files\Internet Explorer\iexplore.exe"
        // ok: csharp_injection_rule-CommandInjection
        p.StartInfo.FileName = @"C:\Program Files\Internet Explorer\iexplore.exe";
        // ok: csharp_injection_rule-CommandInjection
        p.StartInfo.Arguments = "www.example.com";
        p.Start();
    }

    static void ProcessWithStartInfoDirectS2()
    {
        var p = new Process();
        String arguments = "www.example.com";
        String fileName = @"C:\Program Files\Internet Explorer\iexplore.exe";
        // @"C:\Program Files\Internet Explorer\iexplore.exe"
        // ok: csharp_injection_rule-CommandInjection
        p.StartInfo.FileName = fileName;
        // ok: csharp_injection_rule-CommandInjection
        p.StartInfo.Arguments = arguments;
        p.Start();
    }

    static void ProcessWithStartInfoObject()
    {
        // ruleid: csharp_injection_rule-CommandInjection
        ProcessStartInfo info = new ProcessStartInfo(Console.ReadLine());
        // ruleid: csharp_injection_rule-CommandInjection
        info.Arguments = Console.ReadLine();
        // ruleid: csharp_injection_rule-CommandInjection
        Process.Start(info);
    }

    static void ProcessDirectUs()
    {
        // ruleid: csharp_injection_rule-CommandInjection
        Process.Start(Console.ReadLine());
    }

    static void ProcessDirectS()
    {
        // ok: csharp_injection_rule-CommandInjection
        Process.Start("notepad.exe");
    }

    static void Safe()
    {
        var program = "notepad.exe";
		// ok: csharp_injection_rule-CommandInjection
        Process.Start(program);
    }

    static void ProcessWithStartInfoDirectUsingSafe()
    {
        String arguments = "www.example.com";
        String fileName = @"C:\Program Files\Internet Explorer\iexplore.exe";
        using (var p = new Process())
        {
            // @"C:\Program Files\Internet Explorer\iexplore.exe"
            // ok: csharp_injection_rule-CommandInjection
            p.StartInfo.FileName = fileName;
            // ok: csharp_injection_rule-CommandInjection
            p.StartInfo.Arguments = arguments;
            p.Start();
        }
    }

    static void ProcessWithStartInfoDirectUsing()
    {
        using (var p = new Process())
        {
            // @"C:\Program Files\Internet Explorer\iexplore.exe"
            // ruleid: csharp_injection_rule-CommandInjection
            p.StartInfo.FileName = fileName;
            // ruleid: csharp_injection_rule-CommandInjection
            p.StartInfo.Arguments = arguments;
            p.Start();
        }
    }

    static void ProcessWithStartInfoDirectUsingUnSafe2()
    {
        using (Process myProcess = new Process())
        {
            ProcessStartInfo myProcessStartInfo = new ProcessStartInfo();

            // ruleid: csharp_injection_rule-CommandInjection
            myProcessStartInfo.Arguments = Console.ReadLine();
            myProcessStartInfo.UseShellExecute = false;

            myProcessStartInfo.RedirectStandardError = true;
            myProcessStartInfo.RedirectStandardOutput = true;
            myProcess.StartInfo = myProcessStartInfo;
            myProcess.Start();
        }
    }

    private static void processInsideBlock(string arg)
        {
            var process = new Process
            {
                StartInfo = new ProcessStartInfo
                {
                    // ok: csharp_injection_rule-CommandInjection
                    FileName = @"C:\Program Files\Internet Explorer\iexplore.exe",
                    // ruleid: csharp_injection_rule-CommandInjection
                    Arguments = $"{arg}",
                    RedirectStandardOutput = true,
                    UseShellExecute = false,
                    CreateNoWindow = true
                }
            };

            process.Start();
        }
}
