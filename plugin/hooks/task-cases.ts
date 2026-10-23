// ABOUTME: The begin/report cases both implementations of the task note answer to: task.py through tests/test_task.py,
// ABOUTME: task-line.ts through its kit test. JSON after the export, so the Python test reads it with json.loads.
export default [
 {
  "name": "begin starts a task with nothing reported",
  "steps": [
   {
    "verb": "begin",
    "title": "Fix the login bug",
    "now": 1000
   }
  ],
  "expect": {
   "title": "Fix the login bug",
   "activity": null,
   "percent": null,
   "done": false,
   "ts": 1000
  }
 },
 {
  "name": "a report sets activity, percent and time and keeps the task",
  "steps": [
   {
    "verb": "begin",
    "title": "Fix",
    "now": 1000
   },
   {
    "verb": "report",
    "activity": "Reading code",
    "percent": 35,
    "now": 1060
   }
  ],
  "expect": {
   "title": "Fix",
   "activity": "Reading code",
   "percent": 35,
   "done": false,
   "ts": 1060
  }
 },
 {
  "name": "unknown reports an activity with no percent",
  "steps": [
   {
    "verb": "begin",
    "title": "Fix",
    "now": 1000
   },
   {
    "verb": "report",
    "activity": "Assessing task",
    "percent": null,
    "now": 1001
   }
  ],
  "expect": {
   "activity": "Assessing task",
   "percent": null,
   "done": false
  }
 },
 {
  "name": "a hundred means Complete and done",
  "steps": [
   {
    "verb": "begin",
    "title": "Fix",
    "now": 1000
   },
   {
    "verb": "report",
    "activity": "Last check",
    "percent": 100,
    "now": 1500
   }
  ],
  "expect": {
   "activity": "Complete",
   "percent": 100,
   "done": true,
   "ts": 1500
  }
 },
 {
  "name": "a report on a done task is refused",
  "steps": [
   {
    "verb": "begin",
    "title": "Fix",
    "now": 1000
   },
   {
    "verb": "report",
    "activity": "x",
    "percent": 100,
    "now": 1001
   },
   {
    "verb": "report",
    "activity": "More",
    "percent": 50,
    "now": 1002
   }
  ],
  "error": "task is done: begin a new one for more work"
 },
 {
  "name": "begin replaces a finished task",
  "steps": [
   {
    "verb": "begin",
    "title": "One",
    "now": 1000
   },
   {
    "verb": "report",
    "activity": "x",
    "percent": 100,
    "now": 1001
   },
   {
    "verb": "begin",
    "title": "Two",
    "now": 1002
   }
  ],
  "expect": {
   "title": "Two",
   "activity": null,
   "percent": null,
   "done": false,
   "ts": 1002
  }
 },
 {
  "name": "a report without a task is refused",
  "steps": [
   {
    "verb": "report",
    "activity": "Reading",
    "percent": 5,
    "now": 1000
   }
  ],
  "error": "no task yet: run begin first"
 },
 {
  "name": "an empty title is refused",
  "steps": [
   {
    "verb": "begin",
    "title": "   ",
    "now": 1000
   }
  ],
  "error": "title is empty"
 },
 {
  "name": "an activity of bidi marks alone is refused",
  "steps": [
   {
    "verb": "begin",
    "title": "Fix",
    "now": 1000
   },
   {
    "verb": "report",
    "activity": "⁦‮",
    "percent": 5,
    "now": 1001
   }
  ],
  "error": "activity is empty"
 },
 {
  "name": "percent above a hundred is refused",
  "steps": [
   {
    "verb": "begin",
    "title": "Fix",
    "now": 1000
   },
   {
    "verb": "report",
    "activity": "Reading",
    "percent": 120,
    "now": 1001
   }
  ],
  "error": "percent must be 0 to 100"
 },
 {
  "name": "percent below zero is refused",
  "steps": [
   {
    "verb": "begin",
    "title": "Fix",
    "now": 1000
   },
   {
    "verb": "report",
    "activity": "Reading",
    "percent": -1,
    "now": 1001
   }
  ],
  "error": "percent must be 0 to 100"
 },
 {
  "name": "control characters and bidi overrides leave the title",
  "steps": [
   {
    "verb": "begin",
    "title": "Hi\n‮ there\u0007",
    "now": 1000
   }
  ],
  "expect": {
   "title": "Hi there"
  }
 },
 {
  "name": "a title is cut to eighty code points, an emoji intact at the cut",
  "steps": [
   {
    "verb": "begin",
    "title": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx😀tail",
    "now": 1000
   }
  ],
  "expect": {
   "title": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx😀"
  }
 },
 {
  "name": "an activity is cut to forty code points then trimmed",
  "steps": [
   {
    "verb": "begin",
    "title": "Fix",
    "now": 1000
   },
   {
    "verb": "report",
    "activity": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa b",
    "percent": 5,
    "now": 1001
   }
  ],
  "expect": {
   "activity": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  }
 },
 {
  "name": "a refused report leaves the note as it was",
  "steps": [
   {
    "verb": "begin",
    "title": "Fix",
    "now": 1000
   },
   {
    "verb": "report",
    "activity": "Reading",
    "percent": 35,
    "now": 1060
   },
   {
    "verb": "report",
    "activity": "Reading",
    "percent": 101,
    "now": 1070
   }
  ],
  "error": "percent must be 0 to 100",
  "expect": {
   "activity": "Reading",
   "percent": 35,
   "ts": 1060
  }
 }
]
