import { keepPreviousData, useQuery } from '@tanstack/react-query';
import apiClient from '../services/api';
import type { PaginatedResponse, Project, SingleResponse } from '../types';

interface ProjectsQuery {
  page: number;
  pageSize: number;
}

const fetchProjects = async ({ page, pageSize }: ProjectsQuery): Promise<PaginatedResponse<Project>> => {
  const offset = (page - 1) * pageSize;
  const response = await apiClient.get('/projects', {
    params: { limit: pageSize, offset },
  });
  return response.data;
};

export const useProjects = ({ page, pageSize }: ProjectsQuery) => {
  return useQuery({
    queryKey: ['projects', { page, pageSize }],
    queryFn: () => fetchProjects({ page, pageSize }),
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
