import { keepPreviousData, useQuery } from '@tanstack/react-query';
import apiClient from '../services/api';
import type { PaginatedResponse, Project, ProjectStatus, ProjectType, SingleResponse } from '../types';

interface ProjectsQuery {
  page: number;
  pageSize: number;
  searchQuery?: string;
  status?: ProjectStatus;
  projectType?: ProjectType;
  sortBy?: 'name' | 'created_at' | 'updated_at' | 'status' | 'project_type';
  sortDirection?: 'asc' | 'desc';
}

const fetchProjects = async ({
  page,
  pageSize,
  searchQuery,
  status,
  projectType,
  sortBy,
  sortDirection,
}: ProjectsQuery): Promise<PaginatedResponse<Project>> => {
  const offset = (page - 1) * pageSize;
  const response = await apiClient.get('/projects', {
    params: {
      limit: pageSize,
      offset,
      q: searchQuery || undefined,
      status,
      project_type: projectType,
      sort_by: sortBy,
      sort_direction: sortDirection,
    },
  });
  return response.data;
};

export const useProjects = (query: ProjectsQuery) => {
  return useQuery({
    queryKey: ['projects', query],
    queryFn: () => fetchProjects(query),
    placeholderData: keepPreviousData,
  });
};

const fetchProject = async (projectId: string): Promise<SingleResponse<Project>> => {
  const response = await apiClient.get(`/projects/${projectId}`);
  return response.data;
};

export const useProject = (projectId: string) => {
  return useQuery({
    queryKey: ['project', projectId],
    queryFn: () => fetchProject(projectId),
    enabled: !!projectId, // Only run the query if projectId is available
  });
};
