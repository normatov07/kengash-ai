# **goal** from this app: I need to can work with many application the same time with only clude code, antigravity, codex and etc subsciptions by using their cli instead of api.



for this we can use their cli session on our desktop.

step 1:  

for this first we need to create our own AI agent development folder and file structures.  

lets analyse this link:  [https://walkinglabs.github.io/learn-harness-engineering/en/](https://walkinglabs.github.io/learn-harness-engineering/en/) 

[https://www.humanlayer.dev/blog/skill-issue-harness-engineering-for-coding-agents](https://www.humanlayer.dev/blog/skill-issue-harness-engineering-for-coding-agents)

[https://martinfowler.com/bliki/InfrastructureAsCode.html](https://martinfowler.com/bliki/InfrastructureAsCode.html)

[https://www.aihero.dev/skills](https://www.aihero.dev/skills)  

based on this first create [AGENTS.md](http://AGENTS.md) file on root. write the application information for AI agents. then link this files to cloude, codex, gemini default starter files.   

then set up the best filesystem for hanress automation python project.  

we need to docs folder to write sync ever changes on app for every module separated folder.  

set up the best practices writeing md files for instuction ai agents based on responsibilities.  

step 2:  

we build application automate my whole enginering process based on harness and agentic loop.  

the idea is below:  

Analyse the best practises writing skills  

Set max line and words for writing skills detail to minimize toke usage to read skills.  

Write skills with minimum token usage optimize them to giving more responibility to shell commands and tools.  

Analyse the best security and harness enginering principles based on structure open source folder structure.  

Everything should be tool call if we can automate before this task.  

then we need general files which is actively read and change ai agents based on responsibilty of files, all files must be compacted and compressed as much as we could, do not add every thing to these files add important notes with minimal words for token effeciency.:  

[MEMORY.md](http://MEMORY.md) - it is main brain for agent which is save user specific usecases, which is user mood, it is prespectives, current goals, thinkings. this file must be general for ovall over application for needing for general purpouses and update and compacted when needed. when we create app with skill make link to application folder for this file  

[PROCESS.md](http://PROCESS.md) - this is not general file it is specified for ever application to set overall processes of appication  

[DECISITIONS.md](http://DECISITIONS.md) - it is general file track user designs in specific and important designs. it will be linked when app created.  

[SETTINGS.md](http://SETTINGS.md) - it is our settings file which is specific for each application. we have default setting for start up project and it is copied when app or task runns to speciic application if this file is not available if it ia available do not touc it becouse user can change it based on application level.  

step 3:  

Main logic is below:  

When I send a prompt to coding agent it must analyse this by using the best practices then based on task it must create small sub tasks and based on tasks create tickets on memory with specific status.  

we need also event loop count track for every task to limit loop size for avoid infinite looping between agents.  

we need to importantce level for every task. we can set up simple tasks under simpler loop, for more critical or middle level tasks is different loop. for example  

for simple tasks:  

plan  

implement  

review  

and if there are some feedback on review recircle over process.  

for critical task  

plan  

review plan. if some feedback give previus agent fix plan, if no move to next step  

implement  

review code  

security agent review  

etc  

step 4. agent Memory to exchange info multiple sesssion agents.  

we need to use support different kind of memory, for now default md files.  

Important this memory files written in some generl places which os can access write for each application and hard linked to ap[plication folder itself,so we my work both places at once. when our link break or we can nor found tasks of specifica project but its folder has this kind of folder we can use this folder by hard linking to us which is perfectly okay both side hard linking if it is needed.  

we write tasks to md files, we have folders which is describe task statuses. for example, tasks/done, tasks/in_progress, tasks/in_queue to save. in every tasks has statuses for example:  

in_progress -&gt; under_implementation, under_review, under_security review etc it migh be dynamic, based on user settings.  

when tasks successfully finished move this tasks to done folder. for each tasks we need to generate uuid, based on uuid we must find task easily and based on this task in the future review even done tasks etc.  

memory folder structure:  

tasks/&lt;project name or project folder name&gt;/in_process  

tasks/&lt;project name or project folder name&gt;/done  

tasks/&lt;project name or project folder name&gt;/in_queue  

step 5. Agent settings and monitoring  

we must have default settings and agents for all over enginering process and default workfollow over these agents.  

user easly control each agents status (on, off), its model end etc on [settings.md](http://settings.md) file for each application, defult use our default setting for it.  

our goal you know is to use subscription of every popular ai coding agents for example antigravity, cloud code, codex etc by using its cli sessions. based on our agent and its mdels we need to create new session on cli and give specific tasks automatically, watever I mainly use codex, cloude, agy or etc they mainly can controll my prompt and setup agent loop over our settings. they must talk with cli session without openeing new ones each time to minimize context toke usage. when tasks reach max loop to do done task ask from user to approve additional loop to continue task.   

step 6. Task and agent setting and monitoring UI.  

For additionally we have also UI which is controll agents setting, create new agent and change agent collabration flow on the UI.  



first user can show it is default agents setting and models on UI and can change it, when it change we can save them perscistend general memory.  

also he can change all agent prevefences.  

another page we have collabration wrokflow over agents, user can chage agnets steps based on these ui.  

another page we have kanban board like trello to sow all task, status, tags, importance, loop circle count on ui,when press on task it open its details on modal like trell. use teh best practices. aso in detail we need to also see what changes have been made based on this tasks, that is very important.  

add command to skills to install and open UI to manage these UI locally. for example /open-ui command open immadiately already UI installed if not it asks user to install the app after installation open run UI on browser.  

step 7.  

in our skill, we have different kind of commands.  

/to-ticket &lt;prompt&gt; [path to project] - command responsible for prompt to separate tickets and save to memory as one prompt to one file with many tickets, with full details with original prompt.  

/to-loop [project name or folder] - command read all in queue tasks from memory and set up loop to give specific ticket for agent loop, if ticket is relevent each others and can not be implement simultaneously, implement them one by one, is some of them or all is can be implement simultaneously give them multiple agents with new cli seassion each one. when tasks give to agents move the file to /in_process folder with changing tasks metadatas.  

when I run /to-loop without optional attribute folder name read all projects tasks under in_queue folder and set up loop circle.  

if we have folder or project name read only the tasks for this projects and set up tasks.  

SO it is important to well orginize similtanous process of tasks at the same time, becouse my main point I must can work multiple projects tasks at the same time.  

SO my main goal from this app: I need to can work with many application the same time with only clude code, antigravity, codex and etc subsciptions by using their cli.  

And I need to monitor and manage fully by UI this proccess above. it will be open source any developer can use and set up their harness envirement based on my application.  so it must work and use the best practices for efficiency and minimize token usage and increase deleoper productivity and monitoring.  

all tasks and ticket process status and which AI models worked on each steps must be track and other imprtant things also must be trackd and logged into memory for developer monitoring with efficiency.  

Use the best practices. write clean and maintainble code.  

First analyse networks this kind of aplication, theory and other improtant tecnics and tools to implement then design plan and implement step by step. after each implementation review all change critically, then compare it my goal and requirement. use the best practises for it.

you must implement design by this claude design url: [https://claude.ai/artifact/JiMGMkbaw8qhafeaNbqU7d](https://claude.ai/artifact/JiMGMkbaw8qhafeaNbqU7d)

use the best practices and implementing UI design based on above link. use skills if you have for claude design mcp, this is the same account with cloude code.

  